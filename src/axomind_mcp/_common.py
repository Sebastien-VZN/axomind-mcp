"""Axomind MCP — shared configuration and low-level HTTP proxy.

Owns the FastMCP instance, environment-based configuration, and the _post
helper that all tool modules use to reach bot_api.php.

Mindmap layout constants and node expansion helpers live in
config_layout_mindmap.py.
"""

import json
import logging
import os
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("axomind_mcp")

# ──────────────────────────────────────────────
# .env file loader — runs BEFORE reading any env vars
# ──────────────────────────────────────────────

# The .env file path is resolved in priority order:
#   1. AXOMIND_ENV_FILE env var (explicit — recommended for production)
#   2. Standard OS locations (fallback — dev only)
#
# Existing env vars ALWAYS override .env values — an env var explicitly
# set by Hermes config or systemd takes priority over the file.
#
# ⚠️ SECURITY: the fallback paths below are for DEV ONLY. In production,
# set AXOMIND_ENV_FILE explicitly (via systemd Environment= or Hermes config)
# so the path is not discoverable from the public repo source code.

_ENV_FILE_PATHS = [
    Path.home() / ".env",
    Path.cwd() / ".env",
]

_LOADED_ENV_SOURCE: str | None = None


def _loaded_env_source() -> str | None:
    """Return the path of the loaded .env file, or None if not loaded."""
    return _LOADED_ENV_SOURCE


def _load_env_file() -> str | None:
    """Load variables from a .env file into os.environ if present.

    Does NOT overwrite existing env vars — only sets vars that are not
    already in the environment. This means Hermes config.yaml env vars
    always take priority over .env file values.

    Returns the path of the loaded file (str) or None if no file found.
    """
    global _LOADED_ENV_SOURCE

    # 1. Explicit override via env var (highest priority)
    explicit = os.environ.get("AXOMIND_ENV_FILE")
    if explicit:
        p = Path(explicit)
        if p.is_file():
            _load_env_path(p)
            _LOADED_ENV_SOURCE = str(p)
            return str(p)
        # Explicit path given but file doesn't exist — skip standard locations
        # to respect the explicit override
        return None

    # 2. Try standard locations (priority order)
    for p in _ENV_FILE_PATHS:
        if p.is_file():
            _load_env_path(p)
            _LOADED_ENV_SOURCE = str(p)
            return str(p)

    return None


def _load_env_path(path: Path) -> None:
    """Parse a .env file and set missing env vars."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, PermissionError):
        return

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()

        # Strip surrounding quotes
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]

        # Only set if not already in the environment (env vars take priority)
        if key and key not in os.environ:
            os.environ[key] = value


# Load .env file at import time — before any os.environ.get() calls below
_load_env_file()


# ──────────────────────────────────────────────
# Configuration via environment variables
# ──────────────────────────────────────────────

BASE_URL = os.environ.get("AXOMIND_BASE_URL", "")
BOT_ID = os.environ.get("AXOMIND_BOT_ID", "")
BOT_KEY = os.environ.get("AXOMIND_BOT_KEY", "")
TIMEOUT = int(os.environ.get("AXOMIND_TIMEOUT", "30"))

# ──────────────────────────────────────────────
# User API configuration (index.php — not bot_api.php)
# ──────────────────────────────────────────────

# Base URL for the user API (index.php endpoint, not bot_api.php).
# Derived from AXOMIND_BASE_URL if not explicitly set.
USER_BASE_URL = os.environ.get(
    "AXOMIND_USER_BASE_URL",
    BASE_URL.replace("bot_api.php", "index.php") if BASE_URL else "",
)
# Server-side shared key (KEY_PASS) — required for all user API calls.
KEY_PASS = os.environ.get("AXOMIND_KEY_PASS", "")
# Atlas user credentials for login.
USER_EMAIL = os.environ.get("AXOMIND_USER_EMAIL", "")
USER_PASSWORD = os.environ.get("AXOMIND_USER_PASSWORD", "")
# Type client identifier (determines which token column is used server-side).
USER_TYPE_CLIENT = os.environ.get("AXOMIND_USER_TYPE_CLIENT", "")
# Route prefix used by all user API routes (server-side shared secret).
ROUTE_PREFIX = os.environ.get("AXOMIND_ROUTE_PREFIX", "")

# ──────────────────────────────────────────────
# AI backend router
# ──────────────────────────────────────────────

# When True, the daemon does NOT process messages via Ollama. Hermes/Atlas
# (cloud) handles everything — the daemon just holds the WS connection and
# buffers events. Hermes polls them via the user_poll_events MCP tool.
# When False, the daemon processes incoming messages with a local Ollama model.
# Set via the AXOMIND_USE_HERMES env var ("true"/"1"/"yes" → True).
USE_HERMES = os.environ.get("AXOMIND_USE_HERMES", "true").strip().lower() in (
    "true",
    "1",
    "yes",
)

# Single FastMCP instance — all tool modules register on this.
# Instructions are sent to the MCP client (Hermes/Ollama) as global context.
# They must be self-sufficient for any AI to use the tools correctly without
# external documentation.
mcp = FastMCP(
    "axomind",
    instructions=(
        "Axomind MCP — harmless proxy to bot_api.php (bot tools) and index.php (user tools).\n"
        "\n"
        "## Tool categories\n"
        "Bot API (id_bot + key_access): mindmap (6 tools), messenger (4), planning (5), tree (3).\n"
        "User API (KEY_PASS + token): user (9 tools — login, invitations, messaging, WS events).\n"
        "\n"
        "## Workflow: inject directory into mindmap\n"
        "1. tree_scope(root_path, root_title) → reference count (1 root + N dirs + M files).\n"
        "2. inject_directory_to_mindmap(root_path, root_title, id_mindmap) → one-shot scan + read + Quill Delta conversion + sync.\n"
        "3. Compare the returned summary (total_nodes, descriptions_filled, errors) with tree_scope count.\n"
        "   If they match and errors is empty → injection validated. DONE.\n"
        "4. NEVER call get_mindmap to verify an injection. The summary + tree_scope are sufficient.\n"
        "   get_mindmap returns 2 MB+ for large mindmaps — it is for reading nodes before modifications, not for post-injection validation.\n"
        "\n"
        "## Critical rules\n"
        "- sync_nodes is DESTRUCTIVE: it replaces ALL nodes. Always send the complete list.\n"
        "- replace_mindmap validates hierarchy before sending (no forward-refs, no self-refs).\n"
        "- add_nodes appends to existing nodes (non-destructive).\n"
        "- update_nodes_style is the SAFE way to modify style — it reads, patches, and syncs back.\n"
        "- User token expires in 1 day. If a user tool returns auth error → call user_login again.\n"
        "- tree_scope does NOT read file content. inject_directory_to_mindmap does.\n"
        "- Files > 500 KB and non-text formats (.docx, .pdf, images) get nodes with empty descriptions.\n"
        "- Only .md, .markdown, .txt files are read and converted to Quill Delta.\n"
        "\n"
        "## Node format (simplified, for replace_mindmap / add_nodes)\n"
        "[{\"title\": \"Root\", \"parent\": 0, \"size_box\": 2}, {\"title\": \"Child\", \"parent\": 1}]\n"
        "parent = 1-based order_index of parent (0 = root). size_box: 0=normal, 1=category, 2=root.\n"
        "\n"
        "## Quill Delta descriptions\n"
        "The 'descriptions' field is a JSON string of Quill Delta ops: [{\"insert\":\"text\\n\"}].\n"
        "Supported attributes: bold, italic, header (1-3), list (ordered/bullet), blockquote.\n"
        "Removed attributes: strike, code. Never used: background, divider.\n"
        "Markdown links [text](url) are rendered as bold text.\n"
        "\n"
        "## Planning tools (8 total — 5 low-level + 3 high-level)\n"
        "LOW-LEVEL (raw JSON): list_activities, get_activity, add_assignment, update_assignment, delete_assignment.\n"
        "HIGH-LEVEL (human-friendly, PREFER THESE): create_assignment, modify_assignment, verify_assignment.\n"
        "create_assignment(id_activity, user_ids, titre, start_date, end_date, start_hour, start_minute, end_hour, end_minute, weekdays?, notes?) — builds JSON internally.\n"
        "modify_assignment(same + group_id) — updates existing group.\n"
        "verify_assignment(id_activity) — telemetry report.\n"
        "Dates: YYYY-MM-DD strings. Times: hour/minute ints (0-23, 0-59). Weekdays: full names or 3-letter abbrevs (monday/mon, tuesday/tue, ...).\n"
        "Single-day: start_date==end_date, weekdays omitted. Recursive: start_date<end_date, weekdays required.\n"
        "Returns human-readable summary with group ID, total slots, per-slot details.\n"
        "Full architecture: references/planning_architecture.md in the axomind_mcp skill.\n"
        "\n"
        "## WebSocket (hybrid mode)\n"
        "user_login auto-starts a WS listener if AXOMIND_WS_URL is configured.\n"
        "user_poll_events drains the event buffer: {target, service, message, data}.\n"
        "Key services: new_message, demande_invite_user, first_message_wellcome, sync_mindmap_nodes.\n"
        "WS echo suppression: sync_nodes notifications are NOT sent back to the sender (bot owner).\n"
        "\n"
        "## Full documentation\n"
        "Complete tool reference, data formats, source code mappings, and workflows: docs/hermes/mcp-usage.md in the Flutter repo."
    ),
)

# ──────────────────────────────────────────────
# Constants — default node field values
# ──────────────────────────────────────────────

# Default color if not specified
DEFAULT_NODE_COLOR = "0xFF7A8FF5"

# Minimal node template — all fields expected by the Flutter application.
# Used by config_layout_mindmap.py for node expansion.
_NODE_DEFAULTS = {
    "free_link_order_index": "[]",
    "files_attached": "[]",
    "urls_links": "[]",
    "icon_id": 0,
    "type_node_connection": 0,
    "type_line_selector": 0,
    "spacing_nodes_horizontal": 1,
    "spacing_nodes_vertical": 0,
    "radius": 5,
    "border_size": 2,
    "label_size": 12,
    "stroke_width": 2.5,
    "dot_radius": 6,
    "is_write_children": False,
    "active_bg_colors": False,
    "icon_size": 15,
    "italic_text": False,
    "bold_text": False,
    "underline_text": False,
    "logo_size": 15,
    "update_by_user_id": 0,
    "descriptions": "",
    "logo_url": "",
    "is_manual_position": "false",
    "is_reduce_node_child": "false",
}


# ──────────────────────────────────────────────
# Helper — POST to bot_api.php
# ──────────────────────────────────────────────


def _post(route: str, action: str, **kwargs: object) -> str:
    """POST to bot_api.php with the bot's credentials.

    Args:
        route: route name without the api_ prefix (e.g. messenger, mindmap, activity)
        action: type_action (e.g. get_mindmaps, add_message)
        **kwargs: additional POST parameters

    Returns:
        The HTTP response body (JSON string)
    """
    params = {
        "id_bot": BOT_ID,
        "key_access": BOT_KEY,
        "type_action": action,
    }
    params.update({k: str(v) for k, v in kwargs.items()})

    url = f"{BASE_URL}?route=api_{route}"
    try:
        resp = httpx.post(url, data=params, timeout=TIMEOUT)
        return resp.text
    except httpx.HTTPError as e:
        return json.dumps({"error": f"HTTP request failed: {e}"})


# ──────────────────────────────────────────────
# Helper — POST to index.php (user API)
# ──────────────────────────────────────────────

# In-memory session state — populated by user_login, used by all user tools.
_user_session = {
    "user_id": "",
    "token_exchange": "",
    "pseudo_user": "",
    "tag_pseudo": "",
}


def _post_user(route: str, *, require_auth: bool = True, **kwargs: object) -> str:
    """POST to index.php with the user's security credentials.

    Unlike _post() which targets bot_api.php, this helper targets the user API
    (index.php) and sends KEY_PASS + user_id + token_exchange + type_client.

    For routes that don't require an active session (e.g. login), set
    require_auth=False.

    Args:
        route: route name without the prefix (e.g. auth_action, post_invitation)
        require_auth: if True, include user_id + token_exchange from session
        **kwargs: additional POST parameters

    Returns:
        The HTTP response body (JSON string)
    """
    params = {
        "KEY_PASS": KEY_PASS,
        "type_client": USER_TYPE_CLIENT,
    }
    if require_auth:
        params["user_id"] = _user_session["user_id"]
        params["token_exchange"] = _user_session["token_exchange"]
    params.update({k: str(v) for k, v in kwargs.items()})

    url = f"{USER_BASE_URL}?rt={ROUTE_PREFIX}{route}"
    try:
        resp = httpx.post(url, data=params, timeout=TIMEOUT)
        return resp.text
    except httpx.HTTPError as e:
        return json.dumps({"error": f"HTTP request failed: {e}"})


def _update_user_session(user_id: str, token: str, pseudo: str = "", tag: str = "") -> None:
    """Update the in-memory user session after a successful login or renew."""
    _user_session["user_id"] = str(user_id)
    _user_session["token_exchange"] = str(token)
    if pseudo:
        _user_session["pseudo_user"] = pseudo
    if tag:
        _user_session["tag_pseudo"] = tag


def _get_user_session() -> dict:
    """Return the current user session state (read-only snapshot)."""
    return dict(_user_session)