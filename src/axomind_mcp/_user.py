"""Axomind MCP — User tools.

Tools for Atlas acting as a regular Axomind user (not a bot). Covers:
  - Authentication (login, token renewal)
  - Invitations (list pending, accept, refuse)
  - Messaging (list conversations, send messages)

Authentication uses the user API (index.php) with KEY_PASS + user_id +
token_exchange, NOT the bot API (bot_api.php) with id_bot + key_access.

Session state (user_id, token) is kept in-memory in _common._user_session
and populated by user_login(). All authenticated tools read from it.
"""

import json

from axomind_mcp._common import (
    KEY_PASS,
    USER_EMAIL,
    USER_PASSWORD,
    USER_TYPE_CLIENT,
    _get_user_session,
    _post_user,
    _update_user_session,
    mcp,
)


# ──────────────────────────────────────────────
# Tools — Authentication
# ──────────────────────────────────────────────


@mcp.tool()
def user_login() -> str:
    """Authenticate as a user and store the session token.

    Uses the credentials from environment variables (AXOMIND_USER_EMAIL,
    AXOMIND_USER_PASSWORD) to log in via the user API. On success, stores
    user_id + token_exchange in the in-memory session for all subsequent
    user_* tool calls.

    Returns:
        JSON string with login result (return_code, user_id, token_exchange,
        pseudo_user, tag_pseudo) or error.
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
            # Auto-start WS listener in hybrid mode (Hermes).
            # In daemon mode, daemon.py handles the WS lifecycle itself.
            # The listener only starts if AXOMIND_WS_URL is configured.
            _try_start_ws_listener()
    except (json.JSONDecodeError, KeyError):
        pass
    return result


def _try_start_ws_listener() -> None:
    """Try to start the WS listener after login (hybrid Hermes mode).

    Best-effort: if websockets is not installed or WS_URL is not configured,
    the listener silently does not start. The daemon mode handles its own
    WS lifecycle and does not call this.
    """
    try:
        from axomind_mcp.serveur._ws_listener import WS_URL, start_listener
        import asyncio

        if not WS_URL:
            return

        session = _get_user_session()
        if not session["token_exchange"] or not session["user_id"]:
            return

        # Try to get the running event loop. In Hermes stdio mode, there may
        # not be one running yet — create a thread with its own loop.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # We're inside an async context — schedule the task
            asyncio.ensure_future(
                start_listener(
                    token=session["token_exchange"],
                    user_id=session["user_id"],
                    type_client=USER_TYPE_CLIENT,
                )
            )
        else:
            # No running loop — start one in a background thread
            import threading

            def _ws_thread() -> None:
                ws_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(ws_loop)
                ws_loop.run_until_complete(
                    start_listener(
                        token=session["token_exchange"],
                        user_id=session["user_id"],
                        type_client=USER_TYPE_CLIENT,
                    )
                )
                # Keep the loop running for incoming WS messages
                ws_loop.run_forever()

            t = threading.Thread(target=_ws_thread, daemon=True, name="ws-listener")
            t.start()
    except ImportError:
        pass  # websockets not installed — hybrid mode disabled
    except Exception:
        pass  # Best-effort — don't crash login on WS issues


@mcp.tool()
def user_renew_token() -> str:
    """Renew the user session token before it expires (1 day).

    Uses the current in-memory token to get a fresh one. Should be called
    periodically to keep the session alive.

    Returns:
        JSON string with renewed token data or error.
    """
    result = _post_user(
        "auth_action",
        renew_auth="1",
    )
    try:
        data = json.loads(result)
        if data.get("return_code") == 0:
            _update_user_session(
                user_id=data.get("user_id", _get_user_session()["user_id"]),
                token=data.get("token_exchange", ""),
            )
    except (json.JSONDecodeError, KeyError):
        pass
    return result


@mcp.tool()
def user_status() -> str:
    """Check the current user session status.

    Returns whether Atlas is logged in and shows the user_id, pseudo, and tag.
    Does NOT make any HTTP request — purely local state check.

    Returns:
        JSON string with session info.
    """
    session = _get_user_session()
    logged_in = bool(session["user_id"] and session["token_exchange"])
    return json.dumps({
        "logged_in": logged_in,
        "user_id": session["user_id"],
        "pseudo_user": session["pseudo_user"],
        "tag_pseudo": session["tag_pseudo"],
    })


# ──────────────────────────────────────────────
# Tools — Invitations
# ──────────────────────────────────────────────


@mcp.tool()
def user_get_pending_invitations() -> str:
    """List pending invitations addressed to Atlas.

    Returns invitations that other users have sent to Atlas. Each entry
    contains: pending_id, id (sender user_id), pseudo_user, photo_url,
    maj_datetime (sender profile date), pending_datetime (invitation date).

    Returns:
        JSON string with list of pending invitations.
    """
    session = _get_user_session()
    return _post_user(
        "read_users_collaborator",
        get_pending_users=session["user_id"],
    )


@mcp.tool()
def user_accept_invitation(sender_user_id: int) -> str:
    """Accept a pending invitation from another user.

    This creates a permanent relationship (authorized_user_links) and
    automatically creates a 1-to-1 conversation between Atlas and the
    sender.

    Args:
        sender_user_id: The user ID of the person who sent the invitation.
            This is the 'id' field from the entries returned by
            user_get_pending_invitations.

    Returns:
        JSON string — server confirmation with relationship and conversation IDs.
    """
    session = _get_user_session()
    return _post_user(
        "post_invitation",
        valide_invite_user="1",
        sender_user_id=session["user_id"],
        target_user_id=sender_user_id,
        select_lang="fr_FR",
    )


@mcp.tool()
def user_refuse_invitation(sender_user_id: int) -> str:
    """Refuse a pending invitation from another user.

    Removes the pending invitation. No relationship or conversation is created.

    Args:
        sender_user_id: The user ID of the person who sent the invitation.
            This is the 'id' field from the entries returned by
            user_get_pending_invitations.

    Returns:
        JSON string — server confirmation.
    """
    session = _get_user_session()
    return _post_user(
        "post_invitation",
        refus_invite_user="1",
        sender_user_id=session["user_id"],
        target_user_id=sender_user_id,
    )


# ──────────────────────────────────────────────
# Tools — Messaging
# ──────────────────────────────────────────────


@mcp.tool()
def user_get_conversations() -> str:
    """List all conversations Atlas is a participant in.

    Returns the full conversation list with participants, messages, metadata.
    Each conversation object contains: id, titre, participants (user IDs),
    messages array, created_datetime, maj_datetime.

    Requires an active session — call user_login first if not logged in.

    Returns:
        JSON string with conversation list.
    """
    return _post_user(
        "read_conversations",
        get_list="1",
        maj_datetime="1970-01-01T00:00:00Z",
    )


@mcp.tool()
def user_send_message(content_message: str, id_conversation: int) -> str:
    """Send a message in a conversation as a user (not as a bot).

    Atlas writes as a regular user. The message is encrypted server-side.

    Args:
        content_message: Message content (plaintext, encrypted server-side).
        id_conversation: Conversation ID to send the message to.
    """
    session = _get_user_session()
    return _post_user(
        "post_conversation",
        add_message="1",
        message=content_message,
        sender_rel_user_id=session["user_id"],
        rel_id_conversations=id_conversation,
    )


@mcp.tool()
def user_poll_events() -> str:
    """Drain pending WebSocket events received by the WS listener.

    In hybrid mode (Hermes + WS listener), the WS listener runs as a
    background asyncio task and buffers incoming events. This tool drains
    the buffer and returns all events received since the last call.

    Each event is a WebsocketTransit: {target, service, message, data}.
    Key services for messaging:
      - new_message: a new message arrived (check sender_rel_user_id + rel_id_conversations)
      - demande_invite_user: someone sent an invitation
      - first_message_wellcome: someone accepted an invitation
      - update_conversation, delete_focus_group, etc.

    The WS listener must be started first (it auto-starts after user_login
    if AXOMIND_WS_URL is configured). If the listener is not running, returns
    an empty list.

    Returns:
        JSON string with list of events (may be empty).
    """
    from axomind_mcp.serveur._ws_listener import drain_events, get_listener

    listener = get_listener()
    events = drain_events()
    return json.dumps({
        "ws_connected": listener.is_connected if listener else False,
        "events": events,
        "count": len(events),
    })