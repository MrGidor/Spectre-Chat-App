
# Spectre Chat Application

A lightweight, terminal-based real-time chat platform built with Python, Textual, `asyncio`, and SQLite. Features DM channels, server communities, persistent chat logs, unread notifications, and TLS transport encryption.
<img width="1396" height="759" alt="kép" src="https://github.com/user-attachments/assets/ee10a9e6-74a3-41f4-ad5e-46edc0197e9a" />

**Chatting in a server**<br>
<img width="397" height="130" alt="kép" src="https://github.com/user-attachments/assets/07b4e533-9ffe-43bc-b43a-c963fc0b1338" /><br>
**Chatting with an user**<br>
<img width="284" height="101" alt="kép" src="https://github.com/user-attachments/assets/0d175216-5dbb-4059-8433-f43f344ec58d" />


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

> Default port: `8888`<br>
```bash
python3 server.py

```

On startup, the server logs its SHA-256 TLS Fingerprint:
```bash
======================================================================
[*] Encrypted Spectre Community server online on 0.0.0.0:8888
[*] SHA-256 Fingerprint: 4a8f...
[*] Share this fingerprint out-of-band with clients for initial trust.
======================================================================
```
Tip for Admins: Share this hash out-of-band (e.g., via Discord/Matrix) with users connecting for the first time so they can verify it in their TOFU prompt modal.

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

## 📁 Project Configuration Files

| File | Scope | Description |
| --- | --- | --- |
| `config.json` | Client | Stores host, port, username, and anchored server TLS fingerprint. |
| `identity.json` | Client | Contains your unique cryptographic identity token. Ties your username to your identity on servers and can be transferred across computers. |
| `server_config.json` | Server | Server port and binding IP configuration. |
| `chat_data.db` | Server | SQLite database housing channels, messages, user mappings, and servers. |
| `server.crt` / `.key` | Server | TLS certificates auto-generated via OpenSSL. |

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

## ⚡ Protocol & Versioning

Spectre uses explicit protocol version matching (`MAJOR.MINOR`):
* **Major Version Mismatch (`2.x` vs `1.x`):** The server will reject connections with `PROTOCOL_MISMATCH`. This enforces mandatory security updates across both server and client software.
* **Minor Version Updates:** Backward-compatible feature additions or non-breaking protocol enhancements.
* **Release Versioning vs. Protocol Versioning:** Application release versions (`v1.4`) and protocol versions (`2.0`) are decoupled. The release version tracks application updates, while the protocol version strictly enforces network compatibility and security boundaries.

---

## 🛡️ Security & Privacy Notice

* **In-Transit TLS Encryption:** All client-server traffic is encrypted using TLS (`ssl` context).
* **Trust On First Use (TOFU):** Protects against Man-in-the-Middle (MITM) attacks. Upon initial connection, the client displays the server's SHA-256 TLS certificate fingerprint for out-of-band verification and anchors it locally in `config.json`.
* **Token-Based Device Anchoring:** User identity tokens (`identity.json`) are autogenerated via UUIDv4 and locked to your device upon initial registration to prevent unauthorized username impersonation.
* **Storage:** Messages and server metadata are stored locally on the hosting server in SQLite (`chat_data.db`).
