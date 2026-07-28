
# Spectre Chat Application

A lightweight, terminal-based real-time chat platform built with Python, Textual, `asyncio`, and SQLite. Features DM channels, server communities, persistent chat logs, unread notifications, and TLS transport encryption.
<img width="1091" height="547" alt="kép" src="https://github.com/user-attachments/assets/c2e3bf7e-baaf-4d77-96dc-ee704218d260" />

---

## 🚀 Quick Setup Guide (Self-Hosting)

### 1. Prerequisites
- **Python 3.10+**
- **OpenSSL** (for TLS certificate generation)

### 2. Installation
Clone the repository and install the dependencies:

```bash
git clone https://github.com/MrGidor/Spectre-Community.git
cd Spectre-Community

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install required packages
pip install textual rich

```

---

## 🏃 Running the Application

### Starting the Server

Run `server.py`. The server automatically handles database initialization (`chat_data.db`) and self-signed TLS certificate generation (`server.crt`, `server.key`) on its first run:

```bash
python3 server.py

```

> Default port: `8888`

### Launching the Client

Open a new terminal window, activate your virtual environment, and run:

```bash
python3 client.py

```

---

## 🌐 Deploying to a Remote VPS (Linux / `systemd`)

To run the Spectre server continuously on a VPS (e.g., DigitalOcean, Hetzner, Linode):

1. **Configure Firewall:** Open TCP port `8888`:
```bash
sudo ufw allow 8888/tcp
sudo ufw reload

```


2. **Create a Systemd Service:** Create `/etc/systemd/system/spectre.service`:
```ini
[Unit]
Description=Spectre Community Server
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/path/to/Spectre-Community
ExecStart=/path/to/Spectre-Community/venv/bin/python3 /path/to/Spectre-Community/server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target

```


3. **Start the Service:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now spectre

```



---

## 🔑 Commands Reference

Inside the client TUI:

| Command | Description |
| --- | --- |
| `/list` | Show your friends, servers, and channels |
| `/target @username` | Switch active chat target to a DM |
| `/target code` | Switch active chat target to a Server Code |
| `/addfriend @username` | Add a user to your friends list |
| `/createserver <name>` | Create a new server and receive invite code |
| `/join <code>` | Join a server using an invite code |
| `/createchannel <name>` | Create a channel in current server target |
| `/removechannel <name>` | Removes a channel in the current server target |
| `/channel <name>` | Switch active channel within the current server |

| Useful Hotkeys | Description |
| --- | --- |
| `shift+dragclick` | Text selection |
| `shift+ctrl+c` | Copy selected text |
| `shift+ctrl+v` | Paste clipboard text |
| `ctrl+q` | Exit Spectre |
---

## 🛡️ Security & Privacy Notice

* **In-Transit Encryption:** Communication between client and server is encrypted using TLS.
* **Storage:** Messages and server metadata are stored locally on the hosting machine in `chat_data.db`.
