import asyncio
import json
import os
import secrets
import sqlite3
import ssl
import subprocess
import sys
from typing import Dict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CERT_FILE = os.path.join(BASE_DIR, "server.crt")
KEY_FILE = os.path.join(BASE_DIR, "server.key")

def get_clean_env():
    """Remove PyInstaller's library overrides so subprocess calls use system shared libs."""
    env = dict(os.environ)
    if "LD_LIBRARY_PATH_ORIG" in env:
        env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH_ORIG"]
    else:
        env.pop("LD_LIBRARY_PATH", None)
    return env

def ensure_tls_certs():
    """Generates self-signed TLS certificates if they don't exist."""
    if not os.path.exists(CERT_FILE) or not os.path.exists(KEY_FILE):
        print("[+] Generating self-signed TLS certificates...")
        cmd = [
            "openssl", "req", "-x509", "-newkey", "rsa:4096",
            "-keyout", KEY_FILE, "-out", CERT_FILE,
            "-days", "365", "-nodes",
            "-subj", "/CN=localhost"
        ]
        subprocess.run(cmd, check=True, env=get_clean_env())

ensure_tls_certs()

# 3. Initialize SSL Context safely
ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ssl_ctx.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)

def init_db():
    conn = sqlite3.connect("chat_data.db")
    cur = conn.cursor()
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            user_token TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS friends (
            user1 TEXT,
            user2 TEXT,
            PRIMARY KEY (user1, user2)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS blocks (
            blocker TEXT,
            blocked TEXT,
            PRIMARY KEY (blocker, blocked)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS servers (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            owner TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            server_code TEXT,
            channel_name TEXT,
            PRIMARY KEY (server_code, channel_name)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS server_members (
            server_code TEXT,
            username TEXT,
            PRIMARY KEY (server_code, username)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS server_bans (
            server_code TEXT,
            username TEXT,
            PRIMARY KEY (server_code, username)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            msg_type TEXT,
            target TEXT,
            channel TEXT,
            sender TEXT,
            recipient TEXT,
            content TEXT,
            is_read INTEGER DEFAULT 0,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

ACTIVE_USERS: Dict[str, dict] = {}

def check_or_claim_username(username: str, token: str) -> tuple[bool, str]:
    conn = sqlite3.connect("chat_data.db")
    cur = conn.cursor()
    cur.execute("SELECT user_token FROM users WHERE username = ?", (username,))
    row = cur.fetchone()

    if row is None:
        cur.execute("INSERT INTO users (username, user_token) VALUES (?, ?)", (username, token))
        conn.commit()
        conn.close()
        return True, f"Welcome! Username '@{username}' locked to device."
    else:
        conn.close()
        if row[0] == token:
            return True, f"Welcome back, @{username}!"
        else:
            return False, f"[-] Username '@{username}' is taken."

async def send_unread_notifications(username: str):
    if username in ACTIVE_USERS:
        conn = sqlite3.connect("chat_data.db")
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT sender FROM messages 
            WHERE recipient = ? AND msg_type = 'dm' AND is_read = 0
        """, (username,))
        unreads = [r[0] for r in cur.fetchall()]
        conn.close()

        w = ACTIVE_USERS[username]["writer"]
        w.write(json.dumps({"type": "unreads", "senders": unreads}).encode() + b'\n')
        await w.drain()

async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    username = None
    try:
        while True:
            raw_data = await reader.read(8192)
            if not raw_data:
                break
            
            payload = json.loads(raw_data.decode('utf-8'))
            action = payload.get("action")

            if action == "connect":
                req_uname = payload["username"]
                token = payload["token"]
                success, msg = check_or_claim_username(req_uname, token)
                
                if success:
                    username = req_uname
                    ACTIVE_USERS[username] = {"writer": writer, "token": token}
                    writer.write(json.dumps({"status": "ok", "msg": msg}).encode() + b'\n')
                    await writer.drain()
                    await send_unread_notifications(username)
                else:
                    writer.write(json.dumps({"status": "error", "msg": msg}).encode() + b'\n')
                    await writer.drain()
                    break

            elif action == "list_all":
                conn = sqlite3.connect("chat_data.db")
                cur = conn.cursor()
                cur.execute("SELECT user2 FROM friends WHERE user1 = ?", (username,))
                friends = [r[0] for r in cur.fetchall()]
                
                cur.execute("""
                    SELECT s.code, s.name, s.owner 
                    FROM servers s JOIN server_members m ON s.code = m.server_code 
                    WHERE m.username = ?
                """, (username,))
                servers_data = cur.fetchall()
                
                servers_list = []
                for scode, sname, owner in servers_data:
                    cur.execute("SELECT channel_name FROM channels WHERE server_code = ?", (scode,))
                    chs = [r[0] for r in cur.fetchall()]
                    servers_list.append({"code": scode, "name": sname, "owner": owner, "channels": chs})
                conn.close()

                writer.write(json.dumps({
                    "type": "list_response",
                    "friends": friends,
                    "servers": servers_list
                }).encode() + b'\n')
                await writer.drain()

            elif action == "fetch_history":
                target_type = payload.get("target_type")
                target = payload.get("target").lstrip('@')
                channel = payload.get("channel", "general").lstrip('#')

                conn = sqlite3.connect("chat_data.db")
                cur = conn.cursor()

                if target_type == "dm":
                    cur.execute("""
                        UPDATE messages SET is_read = 1 
                        WHERE msg_type = 'dm' AND sender = ? AND recipient = ?
                    """, (target, username))
                    conn.commit()

                    cur.execute("""
                        SELECT sender, content FROM (
                            SELECT id, sender, content FROM messages 
                            WHERE msg_type = 'dm' AND 
                            ((sender = ? AND recipient = ?) OR (sender = ? AND recipient = ?))
                            ORDER BY id DESC LIMIT 100
                        ) ORDER BY id ASC
                    """, (username, target, target, username))
                    
                    history = [{"from": r[0], "content": r[1]} for r in cur.fetchall()]
                    conn.close()

                    writer.write(json.dumps({
                        "type": "history_response",
                        "target": target,
                        "target_type": target_type,
                        "channel": channel,
                        "history": history
                    }).encode() + b'\n')
                    await writer.drain()

                else:
                    # check if server exists
                    cur.execute("SELECT 1 FROM servers WHERE code = ?", (target,))
                    if not cur.fetchone():
                        conn.close()
                        writer.write(json.dumps({
                            "status": "error", 
                            "msg": "[-] Server not found."
                        }).encode() + b'\n')
                        await writer.drain()
                        continue

                    ## check if member
                    cur.execute(
                        "SELECT 1 FROM server_members WHERE server_code = ? AND username = ?", 
                        (target, username)
                    )
                    if not cur.fetchone():
                        conn.close()
                        writer.write(json.dumps({
                            "status": "error", 
                            "msg": "[-] Access denied: You are not a member of this server."
                        }).encode() + b'\n')
                        await writer.drain()
                        continue

                    # Verify channel exists in that server
                    cur.execute(
                        "SELECT 1 FROM channels WHERE server_code = ? AND channel_name = ?", 
                        (target, channel)
                    )
                    if not cur.fetchone():
                        conn.close()
                        writer.write(json.dumps({
                            "status": "error", 
                            "msg": f"[-] Channel #{channel} does not exist on this server."
                        }).encode() + b'\n')
                        await writer.drain()
                        continue

                    cur.execute("""
                        SELECT sender, content FROM (
                            SELECT id, sender, content FROM messages 
                            WHERE msg_type = 'server' AND target = ? AND channel = ?
                            ORDER BY id DESC LIMIT 100
                        ) ORDER BY id ASC
                    """, (target, channel))

                    history = [{"from": r[0], "content": r[1]} for r in cur.fetchall()]
                    conn.close()

                    writer.write(json.dumps({
                        "type": "history_response",
                        "target": target,
                        "target_type": target_type,
                        "channel": channel,
                        "history": history
                    }).encode() + b'\n')
                    await writer.drain()

                await send_unread_notifications(username)

            elif action == "mark_read":
                target = payload.get("target").lstrip('@')
                conn = sqlite3.connect("chat_data.db")
                cur = conn.cursor()
                cur.execute("""
                    UPDATE messages SET is_read = 1 
                    WHERE msg_type = 'dm' AND sender = ? AND recipient = ?
                """, (target, username))
                conn.commit()
                conn.close()
                await send_unread_notifications(username)

            elif action == "add_friend":
                target = payload["target"].lstrip('@')
                conn = sqlite3.connect("chat_data.db")
                cur = conn.cursor()
                cur.execute("INSERT OR IGNORE INTO friends (user1, user2) VALUES (?, ?)", (username, target))
                cur.execute("INSERT OR IGNORE INTO friends (user1, user2) VALUES (?, ?)", (target, username))
                conn.commit()
                conn.close()

                writer.write(json.dumps({"status": "info", "msg": f"[+] Added @{target} to friends!"}).encode() + b'\n')
                await writer.drain()

            elif action == "create_server":
                code = secrets.token_urlsafe(6)
                sname = payload["name"]
                conn = sqlite3.connect("chat_data.db")
                cur = conn.cursor()
                cur.execute("INSERT INTO servers (code, name, owner) VALUES (?, ?, ?)", (code, sname, username))
                cur.execute("INSERT INTO server_members (server_code, username) VALUES (?, ?)", (code, username))
                cur.execute("INSERT INTO channels (server_code, channel_name) VALUES (?, ?)", (code, "general"))
                conn.commit()
                conn.close()

                writer.write(json.dumps({"status": "info", "msg": f"[+] Server '{sname}' created! Code: {code}", "code": code}).encode() + b'\n')
                await writer.drain()

            elif action == "join_server":
                code = payload["code"]
                conn = sqlite3.connect("chat_data.db")
                cur = conn.cursor()
                cur.execute("SELECT name FROM servers WHERE code = ?", (code,))
                srv = cur.fetchone()
                if srv:
                    cur.execute("INSERT OR IGNORE INTO server_members (server_code, username) VALUES (?, ?)", (code, username))
                    conn.commit()
                    msg = f"[+] Joined '{srv[0]}'!"
                else:
                    msg = "[-] Invalid server code."
                conn.close()

                writer.write(json.dumps({"status": "info", "msg": msg}).encode() + b'\n')
                await writer.drain()

            elif action == "create_channel":
                code = payload["code"]
                ch_name = payload["channel"].lstrip('#')

                conn = sqlite3.connect("chat_data.db")
                cur = conn.cursor()

                # Verify that the requester is the server owner
                cur.execute("SELECT owner FROM servers WHERE code = ?", (code,))
                row = cur.fetchone()

                if not row:
                    conn.close()
                    writer.write(json.dumps({"status": "error", "msg": "[-] Server not found."}).encode() + b'\n')
                    await writer.drain()
                    continue

                if row[0] != username:
                    conn.close()
                    writer.write(json.dumps({"status": "error", "msg": "[-] Only the server owner can create channels."}).encode() + b'\n')
                    await writer.drain()
                    continue

                # Proceed to create channel
                cur.execute("INSERT OR IGNORE INTO channels (server_code, channel_name) VALUES (?, ?)", (code, ch_name))
                conn.commit()
                conn.close()

                writer.write(json.dumps({"status": "info", "msg": f"[+] Created channel #{ch_name}"}).encode() + b'\n')
                await writer.drain()

            elif action == "remove_channel":
                code = payload["code"]
                ch_name = payload["channel"].lstrip('#')

                # Prevent deletion of the default fallback channel
                if ch_name == "general":
                    writer.write(json.dumps({
                        "status": "error", 
                        "msg": "[-] Cannot delete the default #general channel."
                    }).encode() + b'\n')
                    await writer.drain()
                    continue

                conn = sqlite3.connect("chat_data.db")
                cur = conn.cursor()

                cur.execute("SELECT owner FROM servers WHERE code = ?", (code,))
                row = cur.fetchone()

                if not row:
                    conn.close()
                    writer.write(json.dumps({"status": "error", "msg": "[-] Server not found."}).encode() + b'\n')
                    await writer.drain()
                    continue

                if row[0] != username:
                    conn.close()
                    writer.write(json.dumps({"status": "error", "msg": "[-] Only the server owner can remove channels."}).encode() + b'\n')
                    await writer.drain()
                    continue

                cur.execute("SELECT 1 FROM channels WHERE server_code = ? AND channel_name = ?", (code, ch_name))
                if not cur.fetchone():
                    conn.close()
                    writer.write(json.dumps({"status": "error", "msg": f"[-] Channel #{ch_name} does not exist."}).encode() + b'\n')
                    await writer.drain()
                    continue

                cur.execute("DELETE FROM channels WHERE server_code = ? AND channel_name = ?", (code, ch_name))
                cur.execute("DELETE FROM messages WHERE msg_type = 'server' AND target = ? AND channel = ?", (code, ch_name))
                conn.commit()
                conn.close()

                writer.write(json.dumps({"status": "info", "msg": f"[+] Channel #{ch_name} and its message history were deleted."}).encode() + b'\n')
                await writer.drain()

            elif action == "send_dm":
                target = payload["target"].lstrip('@')
                content = payload["content"]

                conn = sqlite3.connect("chat_data.db")
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO messages (msg_type, target, sender, recipient, content, is_read)
                    VALUES ('dm', ?, ?, ?, ?, 0)
                """, (target, username, target, content))
                conn.commit()
                conn.close()

                if target in ACTIVE_USERS:
                    t_writer = ACTIVE_USERS[target]["writer"]
                    out = json.dumps({"type": "dm", "from": username, "content": content}) + "\n"
                    t_writer.write(out.encode())
                    await t_writer.drain()
                    await send_unread_notifications(target)

            elif action == "server_msg":
                code = payload["code"]
                channel = payload["channel"].lstrip('#')
                content = payload["content"]

                conn = sqlite3.connect("chat_data.db")
                cur = conn.cursor()
                cur.execute("SELECT s.name FROM servers s JOIN server_members m ON s.code = m.server_code WHERE s.code = ? AND m.username = ?", (code, username))
                srv = cur.fetchone()

                if srv:
                    sname = srv[0]
                    cur.execute("""
                        INSERT INTO messages (msg_type, target, channel, sender, content, is_read)
                        VALUES ('server', ?, ?, ?, ?, 1)
                    """, (code, channel, username, content))
                    conn.commit()

                    cur.execute("SELECT username FROM server_members WHERE server_code = ?", (code,))
                    members = [r[0] for r in cur.fetchall()]
                    
                    out = json.dumps({
                        "type": "server_msg",
                        "server_code": code,
                        "server": sname,
                        "channel": channel,
                        "from": username,
                        "content": content
                    }) + "\n"

                    for member in members:
                        if member in ACTIVE_USERS:
                            m_writer = ACTIVE_USERS[member]["writer"]
                            m_writer.write(out.encode())
                            await m_writer.drain()
                conn.close()

    except Exception:
        pass
    finally:
        if username and username in ACTIVE_USERS:
            del ACTIVE_USERS[username]

async def main():
    server = await asyncio.start_server(handle_client, '0.0.0.0', 8888, ssl=ssl_ctx)
    print("Encrypted Spectre Community server online on port 8888...")
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())