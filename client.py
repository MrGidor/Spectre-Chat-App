import asyncio
import json
import os
import uuid
from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Input, RichLog, Static, Button
import ssl
from rich.markup import escape

IDENTITY_FILE = "identity.json"
CONFIG_FILE = "config.json"

ssl_ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE  # Ignore self-signed cert checks in dev

def get_or_create_identity():
    if os.path.exists(IDENTITY_FILE):
        with open(IDENTITY_FILE, "r") as f:
            return json.load(f).get("token")
    else:
        token = str(uuid.uuid4())
        with open(IDENTITY_FILE, "w") as f:
            json.dump({"token": token}, f)
        return token

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    return None

def save_config(username, host, port):
    with open(CONFIG_FILE, "w") as f:
        json.dump({"username": username, "host": host, "port": port}, f)

class SetupScreen(Screen):
    CSS = """
    SetupScreen {
        align: center middle;
    }
    #setup_dialog {
        padding: 1 2;
        border: thick $background 80%;
        background: $surface;
        width: 50;
        height: auto;
    }
    #setup_title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    .setup_label {
        margin-top: 1;
    }
    #setup_btn {
        margin-top: 2;
        width: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("Spectre Community Setup", id="setup_title")
        yield Static("Username:", classes="setup_label")
        yield Input(value="", id="setup_user", placeholder="e.g. alice")
        yield Static("Server IP:", classes="setup_label")
        yield Input(value="127.0.0.1", id="setup_host")
        yield Static("Port:", classes="setup_label")
        yield Input(value="8888", id="setup_port")
        yield Button("Connect", id="setup_btn", variant="primary")

    def on_button_pressed(self, event):
        self._submit()

    def on_input_submitted(self, event):
        self._submit()

    def _submit(self):
        username = self.query_one("#setup_user", Input).value.strip()
        host = self.query_one("#setup_host", Input).value.strip() or "127.0.0.1"
        port_str = self.query_one("#setup_port", Input).value.strip()
        try:
            port = int(port_str)
        except ValueError:
            port = 8888
            
        if not username or username == "":
            return  

        if not host or host == "":
            return

        if not port_str or port_str == "":
            port_str = "8888"

        save_config(username, host, port)
        self.dismiss((username, host, port))

class SpectreClient(App):
    CSS = """
    #unread_bar {
        background: red;
        color: white;
        height: 1;
        display: none;
    }
    RichLog {
        background: $surface;
        color: $text;
        height: 1fr;
        border: solid green;
    }
    #input_box {
        dock: bottom;
    }
    """

    def __init__(self, username=None, host="127.0.0.1", port=8888):
        super().__init__()
        self.username = username
        self.host = host
        self.port = port
        self.token = get_or_create_identity()
        self.reader = None
        self.writer = None
        self.active_target = None
        self.is_dm = False
        self.active_channel = "general"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="unread_bar")
        yield RichLog(id="chat_log", wrap=True, highlight=True, markup=True)
        yield Input(placeholder="Type message or /command...", id="input_box")
        yield Footer()

    async def on_mount(self) -> None:
        config = load_config()
        if config is None:
            self.push_screen(SetupScreen(), self.on_setup_complete)
        else:
            self.username = config.get("username")
            self.host = config.get("host", "127.0.0.1")
            self.port = config.get("port", 8888)
            if self.username:
                await self.connect_to_server()

    async def connect_to_server(self):
        log = self.query_one(RichLog)
        try:
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port, ssl=ssl_ctx)
            conn_payload = {"action": "connect", "username": self.username, "token": self.token}
            self.writer.write(json.dumps(conn_payload).encode() + b'\n')
            await self.writer.drain()

            log.write("[dim]Commands: /list | /target <@user/user/code> | /addfriend @user | /createserver <name> | /join <code> | /channel <name>[/dim]\n")
            asyncio.create_task(self.listen_server())

            await asyncio.sleep(0.2)
            self.writer.write(json.dumps({"action": "list_all"}).encode() + b'\n')
            await self.writer.drain()
        except Exception as e:
            log.write(f"[bold red]Connection error: {e}[/bold red]")

    def on_setup_complete(self, result):
        if result is None:
            self.exit()
            return
        username, host, port = result
        self.username = username
        self.host = host
        self.port = port
        asyncio.create_task(self.connect_to_server())

    async def switch_target(self, target_str: str):
        clean_target = target_str.lstrip('@')
        
        if target_str.startswith("@") or self.is_dm:
            self.is_dm = True
            self.active_target = clean_target
        else:
            self.is_dm = False
            self.active_target = clean_target
        
        req = {
            "action": "fetch_history",
            "target_type": "dm" if self.is_dm else "server",
            "target": self.active_target,
            "channel": self.active_channel
        }
        self.writer.write(json.dumps(req).encode() + b'\n')
        await self.writer.drain()

    async def listen_server(self):
        log = self.query_one(RichLog)
        bar = self.query_one("#unread_bar")

        while True:
            try:
                line = await self.reader.readline()
                if not line:
                    break
                data = json.loads(line.decode().strip())
                
                if data.get("status") == "error":
                    log.write(f"[bold red]{data['msg']}[/bold red]")
                    break
                elif "msg" in data:
                    log.write(f"[bold yellow]{data['msg']}[/bold yellow]")

                elif data.get("type") == "unreads":
                    senders = data.get("senders", [])
                    if senders:
                        bar.update(f" UNREAD MESSAGES FROM: {', '.join(['@' + s for s in senders])} ")
                        bar.styles.display = "block"
                    else:
                        bar.styles.display = "none"

                elif data.get("type") == "history_response":
                    log.clear()  # FIX: Clear screen before printing fetched history
                    ttype = data["target_type"]
                    tgt = data["target"]
                    chn = data["channel"]
                    
                    if ttype == "dm":
                        log.write(f"[bold underline magenta]=== Chatting with @{tgt} ===[/bold underline magenta]")
                    else:
                        log.write(f"[bold underline cyan]=== Server ({tgt}) #{chn} ===[/bold underline cyan]")

                    for msg in data["history"]:
                        sender = msg["from"]
                        content = msg["content"]
                        if sender == self.username:
                            log.write(f"[bold green]You:[/bold green] {content}")
                        else:
                            log.write(f"[bold yellow]@{sender}:[/bold yellow] {content}")

                elif data.get("type") == "dm":
                    sender = data["from"]
                    content = data["content"]
                    if self.is_dm and self.active_target == sender:
                        log.write(f"[bold yellow]@{sender}:[/bold yellow] {content}")
                        # FIX: Mark read without triggering a full re-render/fetch_history
                        req = {"action": "mark_read", "target": sender}
                        self.writer.write(json.dumps(req).encode() + b'\n')
                        await self.writer.drain()

                elif data.get("type") == "server_msg":
                    scode = data["server_code"]
                    channel = data["channel"]
                    sender = data["from"]
                    content = data["content"]
                    
                    if not self.is_dm and self.active_target == scode and self.active_channel == channel:
                        if sender == self.username:
                            log.write(f"[bold green]You:[/bold green] {escape(content)}")
                        else:
                            # Clean markup formatting + escaping
                            log.write(f"[bold cyan]@{escape(sender)}:[/bold cyan] {escape(content)}")

                elif data.get("type") == "list_response":
                    log.write("\n[bold underline yellow]=== YOUR SERVERS ===[/bold underline yellow]")
                    for srv in data["servers"]:
                        log.write(f"• [bold green]{srv['name']}[/bold green] (Code: [bold cyan]{srv['code']}[/bold cyan]) | Channels: #{', #'.join(srv['channels'])}")
                    log.write("\n[bold underline yellow]=== YOUR FRIENDS ===[/bold underline yellow]")
                    for fr in data["friends"]:
                        log.write(f"• @{fr}")
                    log.write("\n[dim]To target: /target @username OR /target server_code[/dim]\n")

            except Exception:
                break

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        log = self.query_one(RichLog)

        if not text:
            return

        if text.startswith("/"):
            parts = text.split(maxsplit=2)
            cmd = parts[0].lower()

            if cmd == "/list":
                req = {"action": "list_all"}
                self.writer.write(json.dumps(req).encode() + b'\n')
                await self.writer.drain()
            elif cmd == "/addfriend" and len(parts) > 1:
                req = {"action": "add_friend", "target": parts[1]}
                self.writer.write(json.dumps(req).encode() + b'\n')
                await self.writer.drain()
            elif cmd == "/createserver" and len(parts) > 1:
                req = {"action": "create_server", "name": parts[1]}
                self.writer.write(json.dumps(req).encode() + b'\n')
                await self.writer.drain()
            elif cmd == "/join" and len(parts) > 1:
                req = {"action": "join_server", "code": parts[1]}
                self.writer.write(json.dumps(req).encode() + b'\n')
                await self.writer.drain()
                self.is_dm = False
                await self.switch_target(parts[1])
            elif cmd == "/createchannel" and len(parts) > 1:
                if self.is_dm or not self.active_target:
                    log.write("[bold red]Target a server first.[/bold red]")
                    return
                req = {"action": "create_channel", "code": self.active_target, "channel": parts[1]}
                self.writer.write(json.dumps(req).encode() + b'\n')
                await self.writer.drain()
            elif cmd == "/channel" and len(parts) > 1:
                if self.is_dm:
                    log.write("[bold red]Cannot switch channels in a DM.[/bold red]")
                    return
                self.active_channel = parts[1].lstrip('#')
                await self.switch_target(self.active_target)
            elif cmd == "/target" and len(parts) > 1:
                target_arg = parts[1]
                if target_arg.startswith("@"):
                    self.is_dm = True
                else:
                    self.is_dm = False
                await self.switch_target(target_arg)
            else:
                log.write("[bold red]Unknown command.[/bold red]")

        else:
            if not self.active_target:
                log.write("[bold red]No target set! Run /list and /target <user/code>[/bold red]")
                return

            if self.is_dm:
                req = {"action": "send_dm", "target": self.active_target, "content": text}
                log.write(f"[bold green]You:[/bold green] {text}")
            else:
                req = {
                    "action": "server_msg", 
                    "code": self.active_target, 
                    "channel": self.active_channel, 
                    "content": text
                }

            self.writer.write(json.dumps(req).encode() + b'\n')
            await self.writer.drain()

if __name__ == "__main__":
    app = SpectreClient()
    app.run()