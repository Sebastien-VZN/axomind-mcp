"""Axomind MCP server — harmless proxy to bot_api.php.

Receives tool calls from an MCP client (e.g. Hermes), makes an HTTP POST
to bot_api.php with id_bot + key_access, and returns the JSON response.

No business logic lives here — all security and data handling stays on
the PHP side (auth, rate limiting, IP ban, database access).

Architecture
------------
The server is split into five tool modules:

  _mindmap.py    — Mindmap tools (read, write, style)       [bot API]
  _messenger.py  — Messenger tools (send, read, update)     [bot API]
  _planning.py   — Planning / Activity tools (list, assign) [bot API]
  _tree.py       — Directory tree tools (scan, inject)      [local + bot API]
  _user.py       — User tools (login, invitations, chat)    [user API]

The first three target bot_api.php with id_bot + key_access credentials.
The user module targets index.php with KEY_PASS + user_id + token_exchange.
_tree.py does local filesystem scanning (no HTTP for tree_to_mindmap/tree_scope)
but inject_directory_to_mindmap calls sync_nodes (bot API) to push nodes.

Shared configuration, constants, and low-level helpers live in _common.py.
File reading and Quill Delta conversion helpers live in _file_reader.py.
Importing this module triggers registration of all 27 tools on the shared
FastMCP instance.

Tool overview
-------------
Mindmap (6 tools) [bot]:
  - list_mindmaps, get_mindmap     — read
  - sync_nodes, add_nodes          — write (sync = destructive, add = merge)
  - replace_mindmap                — write (full replace, simplified format)
  - update_nodes_style             — safe targeted style update

Messenger (4 tools) [bot]:
  - send_message, get_messages
  - update_message, delete_message

Planning (5 tools) [bot]:
  - list_activities, get_activity
  - add_assignment, update_assignment, delete_assignment

Tree (3 tools) [local + bot]:
  - tree_to_mindmap                — scan dir → JSON nodes (local, no HTTP)
  - tree_scope                     — compact telemetry (local, no HTTP)
  - inject_directory_to_mindmap    — scan + read + inject to mindmap (bot API)

User (9 tools) [user API]:
  - user_login, user_renew_token, user_status   — authentication
  - user_get_pending_invitations                — read invitations
  - user_accept_invitation, user_refuse_invitation  — respond to invitations
  - user_get_conversations, user_send_message   — messaging as a user
  - user_poll_events                            — drain WS event buffer (hybrid mode)

The server also has an autonomous daemon mode (daemon.py) that runs without
Hermes, connecting directly to the WebSocket server and using a local Ollama
model for message processing. See daemon.py for details.
"""

# Importing the tool modules registers their @mcp.tool() decorators
# on the shared FastMCP instance. Order does not matter.
from axomind_mcp import _messenger, _planning, _user  # noqa: F401
from axomind_mcp.mindmap import _mindmap  # noqa: F401
from axomind_mcp.tools import _tree  # noqa: F401

# Re-export public symbols for backward compatibility (tests, external imports).
from axomind_mcp._common import (  # noqa: F401
    BASE_URL,
    BOT_ID,
    BOT_KEY,
    TIMEOUT,
    DEFAULT_NODE_COLOR,
    KEY_PASS,
    USE_HERMES,
    USER_BASE_URL,
    USER_EMAIL,
    USER_PASSWORD,
    USER_TYPE_CLIENT,
    ROUTE_PREFIX,
    _NODE_DEFAULTS,
    _post,
    _post_user,
    _update_user_session,
    _get_user_session,
    mcp,
)
from axomind_mcp.mindmap.config_layout_mindmap import (  # noqa: F401
    _expand_node,
    _build_nodes,
    GRID_CELL,
    DEFAULT_NODE_WIDTH,
    DEFAULT_NODE_HEIGHT,
    LAYOUT_PARAMS,
)
import httpx  # noqa: F401 — re-exported for tests that patch server.httpx

# Re-export tool functions for backward compatibility (tests call server.xxx()).
from axomind_mcp._planning import (  # noqa: F401
    list_activities,
    get_activity,
    add_assignment,
    update_assignment,
    delete_assignment,
)
from axomind_mcp.mindmap._mindmap import (  # noqa: F401
    list_mindmaps,
    get_mindmap,
    sync_nodes,
    add_nodes,
    replace_mindmap,
    update_nodes_style,
)
from axomind_mcp._messenger import (  # noqa: F401
    send_message,
    get_messages,
    update_message,
    delete_message,
)
from axomind_mcp._user import (  # noqa: F401
    user_login,
    user_renew_token,
    user_status,
    user_get_pending_invitations,
    user_accept_invitation,
    user_refuse_invitation,
    user_get_conversations,
    user_send_message,
    user_poll_events,
)
from axomind_mcp.tools._tree import (  # noqa: F401
    tree_to_mindmap,
    tree_scope,
    inject_directory_to_mindmap,
)


def main() -> None:
    """Run the MCP server in stdio mode."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()