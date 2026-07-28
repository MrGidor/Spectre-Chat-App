import asyncio
import json
import os
import uuid
from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Input, RichLog, Static, Button
import ssl
from rich.markup import escape

def get_base_dir():
    """Gets the directory where the binary or script is located."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()
IDENTITY_FILE = os.path.join(BASE_DIR, "identity.json")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

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
            
        if not username:
            return  

        if not host:
            return

        if not port_str:
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
    Footer {
        display: none;
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
        self.ENABLE_COMMANDS_PALETTE = False
        self.active_channel = "general"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="unread_bar")
        yield RichLog(id="chat_log", wrap=True, highlight=True, markup=True, auto_scroll=True)
        yield Input(placeholder="Type message or /command...", id="input_box")
        yield Footer()

    async def send_json(self, payload: dict) -> bool:
        """Safely sends JSON over the socket without crashing the UI on dropped connections."""
        if not self.writer or self.writer.is_closing():
            log = self.query_one(RichLog)
            log.write("[bold red]Not connected to server.[/bold red]")
            return False
        try:
            self.writer.write(json.dumps(payload).encode() + b'\n')
            await self.writer.drain()
            return True
        except (ConnectionResetError, BrokenPipeError, OSError) as e:
            log = self.query_one(RichLog)
            log.write(f"[bold red]Connection lost: {e}[/bold red]")
            if self.writer:
                self.writer.close()
            return False

    async def action_quit(self) -> None:
        """Safely close writer connection before quitting Textual."""
        if self.writer and not self.writer.is_closing():
            self.writer.close()
            await self.writer.wait_closed()
        self.exit()

    async def on_mount(self) -> None:
        
        self.screen.styles.user_select = "text"

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
            
            if await self.send_json(conn_payload):
                log.write("[dim]For a list of commands do: /help | To exit Spectre hit ctrl+q[/dim]\n")
                asyncio.create_task(self.listen_server())

                await asyncio.sleep(0.2)
                await self.send_json({"action": "list_all"})
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
        await self.send_json(req)

    async def listen_server(self):
        log = self.query_one(RichLog)
        bar = self.query_one("#unread_bar")

        while True:
            try:
                line = await self.reader.readline()
                if not line:
                    log.write("[bold red]Server closed the connection.[/bold red]")
                    break
                data = json.loads(line.decode().strip())
                
                if data.get("status") == "error":
                    log.write(f"[bold red]{data['msg']}[/bold red]")
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
                    log.clear()
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
                        req = {"action": "mark_read", "target": sender}
                        await self.send_json(req)

                elif data.get("type") == "server_msg":
                    scode = data["server_code"]
                    channel = data["channel"]
                    sender = data["from"]
                    content = data["content"]
                    
                    if not self.is_dm and self.active_target == scode and self.active_channel == channel:
                        if sender == self.username:
                            log.write(f"[bold green]You:[/bold green] {escape(content)}")
                        else:
                            log.write(f"[bold cyan]@{escape(sender)}:[/bold cyan] {escape(content)}")

                elif data.get("type") == "list_response":
                    log.write("\n[bold underline yellow]=== YOUR SERVERS ===[/bold underline yellow]")
                    for srv in data["servers"]:
                        log.write(f"• [bold green]{srv['name']}[/bold green] (Code: [bold cyan]{srv['code']}[/bold cyan]) | Channels: #{', #'.join(srv['channels'])}")
                    log.write("\n[bold underline yellow]=== YOUR FRIENDS ===[/bold underline yellow]")
                    for fr in data["friends"]:
                        log.write(f"• @{fr}")
                    log.write("\n[dim]To target: /target @username OR /target server_code[/dim]\n")

            except Exception as e:
                log.write(f"[bold red]Listener encountered an error: {e}[/bold red]")
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
            if cmd == "/help":
                log.write("Command List: \n-/help\n-/list\n-/addfirend <@user>\n-/createserver <server_name>\n-/join <server code>\n-/createchannel <channel name>\n-/removechannel <channel name>\n-/channel <target channel>\n-/target <@username / server code>")
                return
            elif cmd == "/list":
                await self.send_json({"action": "list_all"})
            elif cmd == "/addfriend" and len(parts) > 1:
                await self.send_json({"action": "add_friend", "target": parts[1]})
            elif cmd == "/createserver" and len(parts) > 1:
                await self.send_json({"action": "create_server", "name": parts[1]})
            elif cmd == "/join" and len(parts) > 1:
                await self.send_json({"action": "join_server", "code": parts[1]})
            elif cmd == "/createchannel" and len(parts) > 1:
                if self.is_dm or not self.active_target:
                    log.write("[bold red]Target a server first.[/bold red]")
                    return
                await self.send_json({"action": "create_channel", "code": self.active_target, "channel": parts[1]})
            
            elif cmd in ("/deletechannel", "/removechannel") and len(parts) > 1:
                if self.is_dm or not self.active_target:
                    log.write("[bold red]Target a server first.[/bold red]")
                    return
                
                target_channel = parts[1].lstrip('#')
                if target_channel == "general":
                    log.write("[bold red]Cannot delete the default #general channel.[/bold red]")
                    return

                await self.send_json({
                    "action": "remove_channel", 
                    "code": self.active_target, 
                    "channel": target_channel
                })
            # ------------------------------------------

            elif cmd == "/channel" and len(parts) > 1:
                if self.is_dm:
                    log.write("[bold red]Cannot switch channels in a DM.[/bold red]")
                    return
                self.active_channel = parts[1].lstrip('#')
                await self.switch_target(self.active_target)
            elif cmd == "/target" and len(parts) > 1:
                target_arg = parts[1]
                self.is_dm = target_arg.startswith("@")
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

            await self.send_json(req)

if __name__ == "__main__":
    app = SpectreClient()
    app.run()