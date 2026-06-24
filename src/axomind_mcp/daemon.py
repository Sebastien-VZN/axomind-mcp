"""Axomind MCP — Autonomous daemon.

Standalone process that connects Atlas to the Axomind messaging network.
Designed for production servers where Hermes is not installed.

The daemon supports two AI backends, controlled by the AXOMIND_USE_HERMES
env var (bool: "true"/"1"/"yes" → True, default "false"):

  - Hermes mode (USE_HERMES=True): the daemon holds the WS connection and
    buffers events. It does NOT call Ollama. Hermes/Atlas (cloud) polls
    events via the user_poll_events MCP tool and responds directly.
    OLLAMA_URL and OLLAMA_MODEL are NOT required in this mode.

  - Ollama mode (USE_HERMES=False, default): the daemon processes incoming
    messages with a local Ollama model (tool-calling). Fully autonomous,
    no Hermes dependency.

Architecture:
  1. user_login() → get token + user_id
  2. WS listener connects to ws://<host>:8080/ with 3 auth headers
  3. Incoming 'new_message' events (not from Atlas itself):
     - Hermes mode: buffered, no processing
     - Ollama mode: sent to Ollama with tool-calling
  4. Token renewed before 24h expiration

Runs via systemd or PM2.

Usage:
  python -m axomind_mcp.daemon

Env vars (in addition to the MCP ones):
  AXOMIND_USE_HERMES         — "true"/"1"/"yes" to route to Hermes (default: "false")
  AXOMIND_WS_URL             — ws://<host>:8080/ (derived from BASE_URL if not set)
  AXOMIND_OLLAMA_URL         — http://<ollama-host>:11434/v1/chat/completions (Ollama mode only)
  AXOMIND_OLLAMA_MODEL       — model name (Ollama mode only)
  AXOMIND_DAEMON_SYSTEM_PROMPT — (optional) override the default system prompt (Ollama mode only)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from typing import Any

import httpx

from axomind_mcp._common import (
    KEY_PASS,
    USE_HERMES,
    USER_BASE_URL,
    USER_EMAIL,
    USER_PASSWORD,
    USER_TYPE_CLIENT,
    _get_user_session,
    _loaded_env_source,
    _post,
    _post_user,
    _update_user_session,
)
from axomind_mcp._doctrines import DEFAULT_SYSTEM_PROMPT
from axomind_mcp._ollama_tools import OLLAMA_TOOLS
from axomind_mcp.mindmap._mindmap import (
    add_nodes as _mindmap_add_nodes,
    replace_mindmap as _mindmap_replace_mindmap,
    update_nodes_style as _mindmap_update_nodes_style,
)
from axomind_mcp._planning import (
    create_assignment as _planning_create_assignment,
    modify_assignment as _planning_modify_assignment,
    verify_assignment as _planning_verify_assignment,
    read_planning as _planning_read_planning,
)
from axomind_mcp.serveur._ws_listener import (
    WSEvent,
    register_callback,
    start_listener,
    stop_listener,
)

logger = logging.getLogger("axomind_mcp.daemon")

# ──────────────────────────────────────────────
# Ollama configuration
# ──────────────────────────────────────────────

OLLAMA_URL = os.environ.get("AXOMIND_OLLAMA_URL", "")
OLLAMA_MODEL = os.environ.get("AXOMIND_OLLAMA_MODEL", "")
OLLAMA_TIMEOUT = int(os.environ.get("AXOMIND_OLLAMA_TIMEOUT", "120"))
# Token renewal interval (23h — token expires at 24h)
TOKEN_RENEW_INTERVAL = 23 * 3600  # seconds


# ──────────────────────────────────────────────
# System prompt — imported from _doctrines.py
# ──────────────────────────────────────────────

# DEFAULT_SYSTEM_PROMPT is imported from axomind_mcp._doctrines


# ──────────────────────────────────────────────
# Tool result size guard
# ──────────────────────────────────────────────

_MAX_TOOL_RESULT_CHARS = 30_000  # ~30 KB — Ollama context safety


def _truncate_tool_result(result: str, max_chars: int = _MAX_TOOL_RESULT_CHARS) -> str:
    """Truncate a tool result if it exceeds max_chars.

    Appends a note explaining the truncation and suggesting targeted tools.
    """
    if len(result) <= max_chars:
        return result
    truncated = result[:max_chars]
    note = (
        f"\n\n[RESULT TRUNCATED — {len(result)} chars total, showing {max_chars}. "
        "Use get_mindmap_summary or get_node_description for targeted reads.]"
    )
    return truncated + note


def _build_mindmap_summary(raw: str, id_mindmap: int) -> str:
    """Build a compact summary of a mindmap from the raw API response.

    Returns: total_nodes, max_depth, estimated_size_kb, and a list of nodes
    with {order_index, title, parent, size_box, has_description}.
    No descriptions, no positions, no styles — context-safe.
    """
    try:
        data = json.loads(raw)
        nodes = data.get("nodes", [])
        if not isinstance(nodes, list):
            return raw

        compact_nodes = []
        max_depth = 0
        total_desc_bytes = 0
        # Build a set of parent order_indexes for depth calculation
        oi_set = {n.get("order_index", 0) for n in nodes}
        for n in nodes:
            oi = n.get("order_index", 0)
            parent = n.get("parent", 0)
            desc = n.get("descriptions", "")
            has_desc = bool(desc) and desc != "[]" and desc != ""
            if has_desc:
                total_desc_bytes += len(desc)
            # Compute depth by walking up the parent chain
            depth = 0
            current_parent = parent
            visited = set()
            while current_parent in oi_set and current_parent not in visited:
                visited.add(current_parent)
                depth += 1
                # Find the parent's parent
                parent_node = next(
                    (pn for pn in nodes if pn.get("order_index") == current_parent),
                    None,
                )
                if parent_node is None:
                    break
                current_parent = parent_node.get("parent", 0)
            if depth > max_depth:
                max_depth = depth

            compact_nodes.append({
                "order_index": oi,
                "title": n.get("title", ""),
                "parent": parent,
                "size_box": n.get("size_box", 0),
                "has_description": has_desc,
            })

        summary = {
            "id_mindmap": id_mindmap,
            "total_nodes": len(nodes),
            "max_depth": max_depth,
            "estimated_size_kb": round(len(raw) / 1024, 1),
            "nodes": compact_nodes,
            "note": (
                "Compact summary — no descriptions or styles. "
                "Use get_node_description(id_mindmap, order_index) to read a node's content."
            ),
        }
        return json.dumps(summary, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return raw


# ──────────────────────────────────────────────
# Tool execution — direct Python calls (no MCP stdio)
# ──────────────────────────────────────────────


def _execute_tool(name: str, arguments: dict) -> str:
    """Execute a tool call directly by calling the Python functions.

    This bypasses the MCP stdio layer — the daemon calls the same helpers
    (_post_user for user API, _post for bot API) that the MCP tools use.
    """
    session = _get_user_session()

    if name == "send_message":
        return _post_user(
            "post_conversation",
            add_message="1",
            message=arguments.get("content_message", ""),
            sender_rel_user_id=session["user_id"],
            rel_id_conversations=arguments.get("id_conversation", 0),
        )

    elif name == "get_conversations":
        return _post_user(
            "read_conversations",
            get_list="1",
            maj_datetime="1970-01-01T00:00:00Z",
        )

    elif name == "get_pending_invitations":
        return _post_user(
            "read_users_collaborator",
            get_pending_users=session["user_id"],
        )

    elif name == "accept_invitation":
        return _post_user(
            "post_invitation",
            valide_invite_user="1",
            sender_user_id=session["user_id"],
            target_user_id=arguments.get("sender_user_id", 0),
            select_lang="fr_FR",
        )

    elif name == "refuse_invitation":
        return _post_user(
            "post_invitation",
            refus_invite_user="1",
            sender_user_id=session["user_id"],
            target_user_id=arguments.get("sender_user_id", 0),
        )

    # ── Bot API: Mindmap tools (6) ──

    elif name == "list_mindmaps":
        return _post("mindmap", "get_mindmaps")

    elif name == "get_mindmap":
        # Return a compact summary instead of the full JSON.
        # Full mindmap data can be 900KB+ (Quill Delta descriptions) which
        # exceeds Ollama's context limit and causes 400 Bad Request.
        raw = _post("mindmap", "get_mindmap", id_mindmap=arguments.get("id_mindmap", 0))
        return _build_mindmap_summary(raw, arguments.get("id_mindmap", 0))

    elif name == "get_mindmap_summary":
        raw = _post("mindmap", "get_mindmap", id_mindmap=arguments.get("id_mindmap", 0))
        return _build_mindmap_summary(raw, arguments.get("id_mindmap", 0))

    elif name == "get_node_description":
        id_mm = arguments.get("id_mindmap", 0)
        oi = arguments.get("order_index", 0)
        raw = _post("mindmap", "get_mindmap", id_mindmap=id_mm)
        try:
            data = json.loads(raw)
            nodes = data.get("nodes", [])
            if isinstance(nodes, list):
                for n in nodes:
                    if n.get("order_index") == oi:
                        desc = n.get("descriptions", "")
                        if len(desc) > 4000:
                            desc = desc[:4000] + "\n[Description truncated — exceeds 4 KB]"
                        return json.dumps({
                            "id_mindmap": id_mm,
                            "order_index": oi,
                            "title": n.get("title", ""),
                            "description": desc,
                        }, ensure_ascii=False)
                return json.dumps({
                    "error": f"Node with order_index={oi} not found in mindmap {id_mm}",
                })
        except (json.JSONDecodeError, TypeError):
            pass
        return raw

    elif name == "sync_nodes":
        return _post(
            "mindmap",
            "sync_nodes",
            id_mindmap=arguments.get("id_mindmap", 0),
            nodes=arguments.get("nodes", ""),
        )

    elif name == "add_nodes":
        return _mindmap_add_nodes(
            id_mindmap=arguments.get("id_mindmap", 0),
            nodes=arguments.get("nodes", ""),
        )

    elif name == "replace_mindmap":
        return _mindmap_replace_mindmap(
            id_mindmap=arguments.get("id_mindmap", 0),
            nodes=arguments.get("nodes", ""),
        )

    elif name == "update_nodes_style":
        return _mindmap_update_nodes_style(
            id_mindmap=arguments.get("id_mindmap", 0),
            style_updates=arguments.get("style_updates", ""),
        )

    # ── Bot API: Messenger tools (4) ──

    elif name == "bot_send_message":
        return _post(
            "messenger",
            "add_message",
            content_message=arguments.get("content_message", ""),
            id_conversation=arguments.get("id_conversation", 0),
        )

    elif name == "bot_get_messages":
        return _post(
            "messenger",
            "get_messages",
            id_conversation=arguments.get("id_conversation", 0),
        )

    elif name == "bot_update_message":
        return _post(
            "messenger",
            "update_message",
            update_message_id=arguments.get("update_message_id", 0),
            content_message=arguments.get("content_message", ""),
        )

    elif name == "bot_delete_message":
        return _post(
            "messenger",
            "delete_message",
            delete_message_id=arguments.get("delete_message_id", 0),
        )

    # ── Bot API: Planning / Activity tools (5) ──

    elif name == "list_activities":
        return _post("activity", "get_activities")

    elif name == "get_activity":
        return _post("activity", "get_activity", id_activity=arguments.get("id_activity", 0))

    elif name == "add_assignment":
        return _post(
            "activity",
            "add_assignment",
            id_activity=arguments.get("id_activity", 0),
            planning_list=arguments.get("planning_list", ""),
            recursive_group=arguments.get("recursive_group", ""),
        )

    elif name == "update_assignment":
        return _post(
            "activity",
            "update_assignment",
            id_activity=arguments.get("id_activity", 0),
            update_assignement_id=arguments.get("update_assignement_id", 0),
            planning_list=arguments.get("planning_list", ""),
            recursive_group=arguments.get("recursive_group", ""),
        )

    elif name == "delete_assignment":
        return _post(
            "activity",
            "delete_assignment",
            id_activity=arguments.get("id_activity", 0),
            delete_recursive_group_slot=arguments.get("delete_recursive_group_slot", 0),
        )

    # ── Bot API: Planning helpers (3) — human-friendly wrappers ──

    elif name == "verify_assignment":
        return _planning_verify_assignment(id_activity=arguments.get("id_activity", 0))

    elif name == "read_planning":
        return _planning_read_planning(
            year=arguments.get("year", 2026),
            id_activity=arguments.get("id_activity", 0),
        )

    elif name == "create_assignment":
        return _planning_create_assignment(
            id_activity=arguments.get("id_activity", 0),
            user_ids=arguments.get("user_ids", []),
            titre=arguments.get("titre", ""),
            start_date=arguments.get("start_date", ""),
            end_date=arguments.get("end_date", ""),
            start_hour=arguments.get("start_hour", 0),
            start_minute=arguments.get("start_minute", 0),
            end_hour=arguments.get("end_hour", 0),
            end_minute=arguments.get("end_minute", 0),
            weekdays=arguments.get("weekdays", None),
            notes=arguments.get("notes", ""),
        )

    elif name == "modify_assignment":
        return _planning_modify_assignment(
            id_activity=arguments.get("id_activity", 0),
            group_id=arguments.get("group_id", 0),
            user_ids=arguments.get("user_ids", []),
            titre=arguments.get("titre", ""),
            start_date=arguments.get("start_date", ""),
            end_date=arguments.get("end_date", ""),
            start_hour=arguments.get("start_hour", 0),
            start_minute=arguments.get("start_minute", 0),
            end_hour=arguments.get("end_hour", 0),
            end_minute=arguments.get("end_minute", 0),
            weekdays=arguments.get("weekdays", None),
            notes=arguments.get("notes", ""),
        )

    else:
        return json.dumps({"error": f"Unknown tool: {name}"})


# ──────────────────────────────────────────────
# Ollama chat with tool-calling loop
# ──────────────────────────────────────────────


def _call_ollama(messages: list[dict], tools: list[dict] | None = None) -> dict:
    """Call Ollama's OpenAI-compatible chat completions endpoint.

    Returns the raw response JSON. Supports tool-calling via the `tools` parameter.
    """
    payload: dict[str, Any] = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools

    try:
        resp = httpx.post(
            OLLAMA_URL,
            json=payload,
            timeout=OLLAMA_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        logger.error(f"Ollama call failed: {e}")
        return {"error": str(e)}


def _process_message_with_ollama(
    incoming_text: str,
    conversation_id: int,
    sender_id: int,
    sender_name: str,
) -> None:
    """Process an incoming message through Ollama and send the response.

    Implements a tool-calling loop:
    1. Send the incoming message to Ollama with tools available
    2. If Ollama returns tool_calls → execute them → feed results back
    3. Repeat until Ollama returns a plain text response (or no tool_calls)
    4. If the final response contains text → send it as a message
    """
    system_prompt = os.environ.get(
        "AXOMIND_DAEMON_SYSTEM_PROMPT",
        DEFAULT_SYSTEM_PROMPT,
    )

    # Build the conversation context for Ollama
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"New message received in conversation {conversation_id} "
                f"from {sender_name} (user_id={sender_id}):\n"
                f'"{incoming_text}"\n\n'
                f"Respond if relevant. You can use send_message to reply "
                f"with id_conversation={conversation_id}."
            ),
        },
    ]

    # Tool-calling loop (max 5 iterations to prevent infinite loops)
    max_iterations = 8
    for i in range(max_iterations):
        response = _call_ollama(messages, tools=OLLAMA_TOOLS)

        if "error" in response:
            logger.error(f"Ollama error on iteration {i}: {response['error']}")
            return

        choice = response.get("choices", [{}])[0]
        msg: dict[str, Any] = choice.get("message", {})

        # Check if the model wants to call tools
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            # Add the assistant message with tool_calls to the conversation
            messages.append(msg)

            # Execute each tool call and feed results back
            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                try:
                    tool_args = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    tool_args = {}

                logger.info(f"Tool call: {tool_name}({tool_args})")
                result = _truncate_tool_result(_execute_tool(tool_name, tool_args))
                logger.debug(f"Tool result: {result[:200]}...")

                # Add tool result to conversation
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": result,
                })

            # Continue the loop — Ollama will process tool results
            continue

        # No tool calls — check for text response
        content = msg.get("content", "").strip()
        if content:
            # The model generated a text response.
            # If it didn't already call send_message, we send the text ourselves.
            # Check if a send_message tool was called in this conversation
            already_sent = any(
                tc.get("function", {}).get("name") == "send_message"
                for m in messages
                if m.get("role") == "assistant" and m.get("tool_calls")
                for tc in m.get("tool_calls", [])
            )

            if not already_sent and conversation_id > 0:
                logger.info(f"Sending auto-response to conv {conversation_id}: {content[:100]}...")
                _execute_tool("send_message", {
                    "content_message": content,
                    "id_conversation": conversation_id,
                })
            elif already_sent:
                logger.info("Response already sent via tool call")
            else:
                logger.info("No conversation ID — response not sent")

        # Done — no more tool calls
        break

    else:
        logger.warning(f"Tool-calling loop reached max iterations ({max_iterations})")


# ──────────────────────────────────────────────
# WS event handler — filters and dispatches to Ollama
# ──────────────────────────────────────────────


async def _on_ws_event(event: WSEvent) -> None:
    """Handle incoming WS events.

    Only processes 'new_message' events where the sender is NOT Atlas itself.
    Other events (update_message, delete_message, state_clients, etc.) are logged
    but not processed by the daemon.
    """
    session = _get_user_session()
    my_user_id = session.get("user_id", "")

    if event.service == "new_message":
        data = event.data
        if not isinstance(data, dict):
            return

        # Extract message fields — mirrors Message.fromJson (message.dart)
        sender_id = 0
        try:
            sender_id = int(data.get("sender_rel_user_id", 0))
        except (TypeError, ValueError):
            pass

        # Skip our own messages (echo from multi-device or bot sends)
        if str(sender_id) == str(my_user_id):
            logger.debug("Skipping own message")
            return

        # Skip bot messages (sender_rel_bot_id != 0)
        bot_id = 0
        try:
            bot_id = int(data.get("sender_rel_bot_id", 0))
        except (TypeError, ValueError):
            pass
        if bot_id != 0:
            logger.debug(f"Skipping bot message (bot_id={bot_id})")
            return

        conversation_id = 0
        try:
            conversation_id = int(data.get("rel_id_conversations", 0))
        except (TypeError, ValueError):
            pass

        message_text = str(data.get("message", ""))
        sender_name = str(data.get("sender_pseudo", f"user_{sender_id}"))

        logger.info(
            f"New message from {sender_name} (id={sender_id}) "
            f"in conv {conversation_id}: {message_text[:80]}..."
        )

        if USE_HERMES:
            # Hermes mode: do NOT process via Ollama. The event stays in the
            # WS listener buffer. Hermes/Atlas polls it via user_poll_events
            # and responds directly through the MCP tools.
            logger.debug(
                "USE_HERMES=True — event buffered for Hermes, skipping Ollama"
            )
            return

        # Process through Ollama (in a thread to not block the async loop)
        await asyncio.to_thread(
            _process_message_with_ollama,
            message_text,
            conversation_id,
            sender_id,
            sender_name,
        )

    elif event.service == "demande_invite_user":
        # New invitation received — log it, Ollama can decide later
        logger.info(f"Invitation received: {event.message}")

    elif event.service == "first_message_wellcome":
        # Invitation accepted by someone — log it
        logger.info(f"Invitation accepted: {event.message}")

    else:
        logger.debug(f"WS event ignored (service={event.service})")


# ──────────────────────────────────────────────
# Token renewal — periodic check
# ──────────────────────────────────────────────


async def _token_renewal_loop() -> None:
    """Periodically renew the user token before it expires (24h)."""
    while True:
        await asyncio.sleep(TOKEN_RENEW_INTERVAL)
        logger.info("Renewing user token...")
        try:
            result = _post_user("auth_action", renew_auth="1")
            data = json.loads(result)
            if data.get("return_code") == 0:
                _update_user_session(
                    user_id=data.get("user_id", _get_user_session()["user_id"]),
                    token=data.get("token_exchange", ""),
                )
                logger.info("Token renewed successfully")
            else:
                logger.error(f"Token renewal failed: {result}")
        except Exception as e:
            logger.error(f"Token renewal error: {e}")


# ──────────────────────────────────────────────
# Login — uses the same flow as _user.py user_login()
# ──────────────────────────────────────────────


def _do_login() -> bool:
    """Authenticate as user and populate the session.

    Returns True on success, False on failure.
    """
    result = _post_user(
        "auth_action",
        require_auth=False,
        email_user=USER_EMAIL,
        pre_auth="1",
        password=USER_PASSWORD,
    )
    try:
        data = json.loads(result)
        if data.get("return_code") == 0:
            _update_user_session(
                user_id=data["user_id"],
                token=data["token_exchange"],
                pseudo=data.get("pseudo_user", ""),
                tag=data.get("tag_pseudo", ""),
            )
            logger.info(
                f"Login successful — user_id={data['user_id']}, "
                f"pseudo={data.get('pseudo_user', '')}"
            )
            return True
        else:
            code = data.get("return_code")
            reason = _LOGIN_CODES.get(code, f"Unknown code: {code}")
            logger.error(f"Login failed: return_code={code} — {reason}")
            return False
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(
            f"Login parse error: {e}\n"
            "  This usually means the server returned HTML instead of JSON.\n"
            "  Check AXOMIND_ROUTE_PREFIX and AXOMIND_BASE_URL in /etc/axomind/.env"
        )
        return False


# ──────────────────────────────────────────────
# Main daemon loop
# ──────────────────────────────────────────────


async def _daemon_main() -> None:
    """Main daemon coroutine: login → start WS → register callback → wait."""
    # 1. Login
    if not _do_login():
        logger.error("Cannot start daemon — login failed")
        sys.exit(1)

    session = _get_user_session()

    # 2. Register the WS event callback (before connecting)
    register_callback(_on_ws_event)

    # 3. Start the WS listener
    await start_listener(
        token=session["token_exchange"],
        user_id=session["user_id"],
        type_client=USER_TYPE_CLIENT,
    )

    # 4. Start token renewal in background
    renewal_task = asyncio.create_task(_token_renewal_loop())

    logger.info(
        f"Daemon started — Atlas listening on WS "
        f"(mode={'hermes' if USE_HERMES else 'ollama'}, "
        f"model={OLLAMA_MODEL if not USE_HERMES else 'N/A'}, "
        f"ollama={OLLAMA_URL if not USE_HERMES else 'N/A'})"
    )

    # 5. Wait forever (until interrupted)
    try:
        await asyncio.Event().wait()  # blocks forever
    except asyncio.CancelledError:
        pass
    finally:
        renewal_task.cancel()
        await stop_listener()
        logger.info("Daemon stopped")


def _validate_env() -> bool:
    """Validate that all required env vars are present.

    Returns True if all OK, False otherwise. Logs clear messages.
    """
    # Core vars (always required)
    core_required = [
        ("AXOMIND_BASE_URL", "URL to bot_api.php (e.g. http://host/app/bot_api.php)"),
        ("AXOMIND_BOT_ID", "Bot ID (from Axomind UI)"),
        ("AXOMIND_BOT_KEY", "Bot access key"),
        ("AXOMIND_KEY_PASS", "Server-side shared key (KEY_PASS)"),
        ("AXOMIND_USER_EMAIL", "Atlas user email"),
        ("AXOMIND_USER_PASSWORD", "Atlas user password"),
        ("AXOMIND_USER_TYPE_CLIENT", "Client type identifier (e.g. axomind_desktop)"),
        ("AXOMIND_ROUTE_PREFIX", "Route prefix for user API (see config_server.php SUFIX_ROUTE constant)"),
        ("AXOMIND_WS_URL", "WebSocket URL (e.g. ws://host:8080/)"),
    ]

    # Ollama vars (only required in Ollama mode)
    ollama_required = [
        ("AXOMIND_OLLAMA_URL", "Ollama API endpoint (must end with /v1/chat/completions)"),
        ("AXOMIND_OLLAMA_MODEL", "Ollama model tag (exact tag from ollama list)"),
    ]

    missing = []
    for var, desc in core_required:
        if not os.environ.get(var):
            missing.append(f"  {var} — {desc}")

    if not USE_HERMES:
        for var, desc in ollama_required:
            if not os.environ.get(var):
                missing.append(f"  {var} — {desc}")

    if missing:
        env_source = _loaded_env_source() or "no .env file found"
        logger.error(
            f"Missing {len(missing)} required environment variable(s):\n"
            + "\n".join(missing)
            + f"\n\n  Source loaded: {env_source}"
            + "\n  Configure them in /etc/axomind/.env (see .env.example in the repo)"
            + " or set them as OS environment variables."
        )
        return False

    return True


def _check_ollama() -> bool:
    """Test the Ollama service by sending a minimal chat request.

    Sends a tiny "ping" message to verify that the Ollama endpoint is
    reachable and the model is loaded. Only called in Ollama mode
    (USE_HERMES=False).

    Returns True if Ollama responded, False otherwise. Logs clear messages.
    """
    logger.info(f"Testing Ollama service at {OLLAMA_URL} (model={OLLAMA_MODEL})...")
    try:
        resp = httpx.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": "ping"}],
                "stream": False,
            },
            timeout=OLLAMA_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        content = (
            data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if "choices" in data
            else data.get("message", {}).get("content", "")
        )
        if not content and "error" in data:
            logger.error(f"Ollama returned an error: {data['error']}")
            return False
        logger.info(
            f"Ollama service OK — model responded "
            f"(reply length={len(content)} chars)"
        )
        return True
    except httpx.ConnectError:
        logger.error(
            f"Cannot connect to Ollama at {OLLAMA_URL}\n"
            "  Check that Ollama is running and the URL is correct.\n"
            "  Verify with: curl -s <ollama_host>:11434/api/tags | jq '.models[].name'\n"
            "  If the model is not listed, pull it: ollama pull <model_tag>"
        )
        return False
    except httpx.HTTPStatusError as e:
        logger.error(
            f"Ollama returned HTTP {e.response.status_code}\n"
            "  This usually means the model tag is wrong or not pulled.\n"
            f"  Check available models: curl -s {OLLAMA_URL.rsplit('/', 3)[0]}://"
            f"{OLLAMA_URL.split('//')[1].rsplit('/', 3)[0]}/api/tags\n"
            "  Pull the model if needed: ollama pull <model_tag>"
        )
        return False
    except httpx.HTTPError as e:
        logger.error(
            f"Ollama service check failed: {e}\n"
            "  The Ollama endpoint may be down or the model may not be loaded."
        )
        return False


# Login return codes for human-readable error messages
_LOGIN_CODES = {
    0: "Success",
    1: "Invalid credentials",
    2: "Email not validated",
    3: "Ban alert — too many attempts",
    5: "2FA required (PIN by mail)",
    6: "IP banned",
    12: "Password change in progress",
}


def main() -> None:
    """Entry point for the autonomous daemon.

    Run with: python -m axomind_mcp.daemon
    Or via the axomind-daemon script in pyproject.toml.

    The daemon loads credentials from /etc/axomind/.env (or a fallback .env file).
    It does NOT accept credentials on the command line or in the script.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 1. Report .env source
    if _loaded_env_source():
        logger.info(f"Environment loaded from: {_loaded_env_source()}")
    else:
        logger.info("No .env file found — using OS environment variables only")

    # 2. Validate all required vars
    if not _validate_env():
        sys.exit(1)

    logger.info(
        f"Variables validated — mode={'hermes' if USE_HERMES else 'ollama'}, "
        f"model={OLLAMA_MODEL if not USE_HERMES else 'N/A'}, "
        f"ollama={OLLAMA_URL if not USE_HERMES else 'N/A'}"
    )

    # 2b. Test Ollama service (Ollama mode only)
    if not USE_HERMES:
        if not _check_ollama():
            logger.error(
                "Ollama service is not available. The daemon cannot process "
                "messages without a working AI backend.\n"
                "  Fix: ensure Ollama is running and the model is pulled.\n"
                "  Or switch to Hermes mode by setting AXOMIND_USE_HERMES=true."
            )
            sys.exit(1)

    # 3. Test user login
    logger.info("Testing user login...")
    if not _do_login():
        # _do_login already logged the error code — add the human-readable hint
        logger.error(
            "Login failed. Check AXOMIND_USER_EMAIL, AXOMIND_USER_PASSWORD, "
            "AXOMIND_KEY_PASS, and AXOMIND_ROUTE_PREFIX in /etc/axomind/.env"
        )
        sys.exit(1)

    # 4. Start the daemon
    try:
        asyncio.run(_daemon_main())
    except KeyboardInterrupt:
        logger.info("Daemon interrupted by user")


if __name__ == "__main__":
    main()