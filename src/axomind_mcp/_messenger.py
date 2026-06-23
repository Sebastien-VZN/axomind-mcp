"""Axomind MCP — Messenger tools.

Tools for sending, reading, updating, and deleting bot messages
in conversations. All tools register on the shared FastMCP instance.
"""

from axomind_mcp._common import _post, mcp


# ──────────────────────────────────────────────
# Tools — Messenger
# ──────────────────────────────────────────────


@mcp.tool()
def send_message(content_message: str, id_conversation: int = 0) -> str:
    """Send a message to a conversation as the bot.

    The message is sent on behalf of the bot assigned to the conversation.
    Content is plaintext — the server encrypts it before storage.

    Args:
        content_message: Message content (plaintext, encrypted server-side)
        id_conversation: Conversation ID (0 = broadcast to all assigned conversations)

    Returns:
        JSON string — server confirmation with message ID.
    """
    return _post(
        "messenger",
        "add_message",
        content_message=content_message,
        id_conversation=id_conversation,
    )


@mcp.tool()
def get_messages(id_conversation: int) -> str:
    """Read bot messages in a conversation.

    Returns messages sent by the bot in the specified conversation. Each
    message object contains: id, content_message, id_conversation,
    rel_id_bot, created_datetime, maj_datetime.

    Args:
        id_conversation: Conversation ID

    Returns:
        JSON string — array of bot message objects.
    """
    return _post("messenger", "get_messages", id_conversation=id_conversation)


@mcp.tool()
def update_message(update_message_id: int, content_message: str) -> str:
    """Update a bot message.

    Replaces the content of an existing bot message. Only messages sent
    by the bot can be updated (use user_send_message for user messages).

    Args:
        update_message_id: Message ID to update
        content_message: New content (plaintext)

    Returns:
        JSON string — server confirmation.
    """
    return _post(
        "messenger",
        "update_message",
        update_message_id=update_message_id,
        content_message=content_message,
    )


@mcp.tool()
def delete_message(delete_message_id: int) -> str:
    """Delete a bot message.

    Removes a message sent by the bot. Only bot messages can be deleted
    with this tool (use the user API for user messages).

    Args:
        delete_message_id: Message ID to delete

    Returns:
        JSON string — server confirmation.
    """
    return _post("messenger", "delete_message", delete_message_id=delete_message_id)