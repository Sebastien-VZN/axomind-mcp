<div align="center">
  <img src="image/logo_axomind.png" alt="Axomind Logo" width="150"/>
  <h1>axomind-mcp</h1>
  <p><strong>MCP server (Model Context Protocol) for Axomind — a harmless proxy to the Bot API.</strong></p>
</div>

---

## Principle

The MCP lives on the **consumer side**, not on the Axomind server. It contains no business logic — it makes an HTTP POST to `bot_api.php` with `id_bot` + `key_access` and returns the JSON. All security (auth, rate limiting, IP bans, `bots @>` checks) stays on the PHP side.

```
AI (Hermes/Atlas)
  → stdio → MCP server Python (FastMCP)
    → HTTP POST → bot_api.php (lib_api_access/*)
      → PHP does the work (auth, DB, WS notify)
    ← JSON response
  ← MCP tool result → AI
```

## Installation

```bash
uv pip install -e .
```

Dependencies: `mcp` (official SDK), `httpx` (HTTP client).

## Configuration

Copy `.env.example` to `.env` and fill in the bot credentials:

```bash
cp .env.example .env
```

Variables:
- `AXOMIND_BASE_URL` — URL to `bot_api.php` (e.g. `http://xx.xx.xx.xx/app/bot_api.php`)
- `AXOMIND_BOT_ID` — Bot ID (from Axomind UI → bot management)
- `AXOMIND_BOT_KEY` — Bot access key
- `AXOMIND_TIMEOUT` — HTTP timeout in seconds (default: 30)

## Available tools (14)

### Activity / Planning (5)

| Tool | Description |
|---|---|
| `list_activities` | List activities where the bot is assigned |
| `get_activity` | Read a specific activity |
| `add_assignment` | Assign time slots to an activity |
| `update_assignment` | Update an assignment group |
| `delete_assignment` | Delete an assignment group |

### Mindmap (5)

| Tool | Description |
|---|---|
| `list_mindmaps` | List mindmaps where the bot is assigned |
| `get_mindmap` | Read a mindmap (metadata + nodes) |
| `replace_mindmap` | **Replace all nodes (simplified format)** — the AI only needs `{title, parent, color?, size_box?}` |
| `add_nodes` | **Append nodes to an existing mindmap (simplified format)** |
| `sync_nodes` | Raw sync (full node JSON, for advanced use) |

#### Simplified format for `replace_mindmap` / `add_nodes`

The AI provides a compact JSON — the MCP auto-expands ~25 default fields:

```json
[
  {"title": "Root", "parent": 0, "color": "0xFFF0BA6D", "size_box": 2, "bold": true},
  {"title": "Category A", "parent": 1, "color": "0xFF7A8FF5", "size_box": 1, "line_style": 1},
  {"title": "Item 1", "parent": 2},
  {"title": "Item 2", "parent": 2, "color": "0xFFFF6F91", "free_links": [3]}
]
```

Fields:
- `title` (required) — node title
- `parent` (required) — order_index of the parent node (0 = root, 1 = first node)
- `color` (optional) — hex color (default: `0xFF7A8FF5`)
- `pos_x`, `pos_y` (optional) — canvas position (default: 0)
- `size_box` (optional) — 0=normal, 1=category, 2=root (default: 0)
- `bold`, `italic`, `underline` (optional) — text style
- `line_type` (optional) — 0=curve, 1=rounded, 2=square
- `line_style` (optional) — 0=solid, 1=dashed
- `stroke_width`, `dot_radius`, `radius`, `border_size`, `label_size` (optional)
- `icon_id` (optional) — icon ID
- `active_bg_colors` (optional) — active background colors
- `descriptions` (optional) — descriptive text
- `free_links` (optional) — list of order_index for free links between nodes

UID and order_index are assigned automatically. `add_nodes` reads the existing mindmap and appends after existing nodes.

### Messenger (4)

| Tool | Description |
|---|---|
| `send_message` | Send a message (targeted or broadcast) |
| `get_messages` | Read bot messages in a conversation |
| `update_message` | Update a bot message |
| `delete_message` | Delete a bot message |

## Tests

```bash
PYTHONPATH=src python -m pytest tests/ -v
```

31 tests — mock httpx, no network calls to the Axomind server.

## Configuration

All configuration is via environment variables. Copy `.env.example` to `.env` and fill in your values, or set them in the Hermes config (see below).

### Bot API (bot_api.php)

| Variable | Required | Description |
|---|---|---|
| `AXOMIND_BASE_URL` | ✅ | URL to `bot_api.php` (e.g. `http://host/app/bot_api.php`) |
| `AXOMIND_BOT_ID` | ✅ | Bot ID (from Axomind UI → bot management) |
| `AXOMIND_BOT_KEY` | ✅ | Bot access key |
| `AXOMIND_TIMEOUT` | ❌ | HTTP timeout in seconds (default: 30) |

### User API (index.php — Atlas messaging)

| Variable | Required | Description |
|---|---|---|
| `AXOMIND_KEY_PASS` | ✅ | Shared key (KEY_PASS) for all user API calls |
| `AXOMIND_USER_EMAIL` | ✅ | Atlas user email |
| `AXOMIND_USER_PASSWORD` | ✅ | Atlas user password |
| `AXOMIND_USER_TYPE_CLIENT` | ✅ | Client type identifier (e.g. `axomind_desktop`) |
| `AXOMIND_ROUTE_PREFIX` | ✅ | Route prefix for user API routes. Found in `app/core/_main/config_server.php` → `SUFIX_ROUTE` constant. Default: `<your_route_prefix>` |
| `AXOMIND_USER_BASE_URL` | ❌ | Override user API base URL (defaults to `BASE_URL` with `bot_api.php` → `index.php`) |

### Daemon mode (autonomous, without Hermes)

| Variable | Required | Description |
|---|---|---|
| `AXOMIND_OLLAMA_URL` | ✅ | Ollama API endpoint (must end with `/v1/chat/completions`) |
| `AXOMIND_OLLAMA_MODEL` | ✅ | Ollama model tag (exact tag from `ollama list`, include quantization suffix) |
| `AXOMIND_OLLAMA_TIMEOUT` | ❌ | Ollama request timeout in seconds (default: 120) |
| `AXOMIND_WS_URL` | ✅ | WebSocket URL for real-time events (e.g. `ws://host:8080/`) |

⚠️ `AXOMIND_ROUTE_PREFIX` is **mandatory** — without it, user API calls (login, messaging, invitations) get a 404 because the URL is built as `{USER_BASE_URL}?rt={ROUTE_PREFIX}{route}`. The prefix is the server-side shared secret that prevents unauthorized route access.

## Daemon deployment (autonomous, without Hermes)

The daemon reads credentials from a `.env` file. The path is resolved in this order:

1. `AXOMIND_ENV_FILE` env var (explicit — production)
2. `~/.env` (dev fallback)
3. `.env` in the CWD (dev fallback)

⚠️ The path to the production `.env` is **never hardcoded** in the source code — set it via `AXOMIND_ENV_FILE` so it is not discoverable from the public repo.

### Setup

1. Create the `.env` file with the `AXOMIND_*` variables (see `.env.example`)
2. Install websockets: `uv pip install --system --break-system-packages websockets`
3. Set the env file path system-wide (see below)
4. Launch: `python -m axomind_mcp.daemon` or `bash scripts/start_daemon.sh`

The daemon will:
- Load the `.env` file (from `AXOMIND_ENV_FILE` or dev fallback)
- Validate all required variables — clear error if any are missing
- Test user login — clear error with return code if it fails
- Connect to WebSocket and start listening

### Setting AXOMIND_ENV_FILE on Debian

#### Option A — System-wide (all users, all services)

```bash
echo 'AXOMIND_ENV_FILE="/etc/axomind/.env"' | sudo tee /etc/environment.d/axomind-mcp.conf
```

Reboot or re-login for the variable to take effect. All processes (daemon, systemd, shell) will inherit it.

#### Option B — Single user (shell profile)

```bash
echo 'export AXOMIND_ENV_FILE="/etc/axomind/.env"' >> ~/.bashrc
source ~/.bashrc
```

#### Option C — systemd service only

```ini
# /etc/systemd/system/axomind-mcp.service
[Service]
Environment=AXOMIND_ENV_FILE=/etc/axomind/.env
ExecStart=/usr/bin/python3 -m axomind_mcp.daemon
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now axomind-mcp
```

### Env var priority

OS env vars > `.env` file. systemd `Environment=` or Hermes config.yaml always override .env file values.

## Hermes configuration

In `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  axomind:
    command: "python3"
    args: ["-m", "axomind_mcp.serveur.server"]
    env:
      # Bot API
      AXOMIND_BASE_URL: "http://xx.xx.xx.xx/app/bot_api.php"
      AXOMIND_BOT_ID: "72"
      AXOMIND_BOT_KEY: "your_key_access"
      # User API
      AXOMIND_KEY_PASS: "your_keypass"
      AXOMIND_USER_EMAIL: "your_bot_email"
      AXOMIND_USER_PASSWORD: "your_bot_password"
      AXOMIND_USER_TYPE_CLIENT: "axomind_desktop"
      AXOMIND_ROUTE_PREFIX: "<your_route_prefix>"
      # Daemon mode
      AXOMIND_OLLAMA_URL: "http://your-ollama-host:11434/v1/chat/completions"
      AXOMIND_OLLAMA_MODEL: "your_model_tag"
      AXOMIND_OLLAMA_TIMEOUT: "120"
      AXOMIND_WS_URL: "ws://your-server:8080/"
      # Python
      PYTHONPATH: "/path/to/axomind-mcp/src"
    workdir: "/path/to/axomind-mcp"
```

⚠️ All `env` values must be strings (YAML parses `72` as int → pydantic rejects it).
⚠️ `PYTHONPATH` is required — `workdir` sets the cwd but not the Python import path.
⚠️ `AXOMIND_ROUTE_PREFIX` is required for all user API tools (login, messaging, invitations). Without it, the daemon and user tools get 404 errors.

To add a missing env var to an existing Hermes config:
```bash
hermes config set mcp_servers.axomind.env.AXOMIND_ROUTE_PREFIX "<your_route_prefix>"
```

Restart Hermes → tools are discovered automatically with the `mcp_axomind_` prefix.

## Security

- The MCP does not touch the database, read files, or contain any business logic
- Credentials come from environment variables
- The Axomind server cannot tell it's a MCP — it sees normal bot_api requests
- The MCP does not run on production — zero additional attack surface

## License

Proprietary — see [LICENSE](LICENSE). Copyright © 2025 VEZZANI Sébastien. All rights reserved.

---

<div align="center">
  <a href="https://sebastien-vezzani.xyz/" target="_blank"><img src="https://img.shields.io/badge/Portfolio-3423A6?style=for-the-badge&logo=firefox-browser&logoColor=white" alt="Link to Portfolio"/></a>
</div>