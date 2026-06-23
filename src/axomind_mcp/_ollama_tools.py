"""Ollama tool definitions (OpenAI tool-calling format).

These definitions describe the tools available to the autonomous daemon
when it processes messages via a local Ollama model. They mirror the
MCP tools exposed to Hermes — both user API tools (messaging, invitations)
and bot API tools (mindmaps, activities, planning, bot messenger).

Kept in a separate module so daemon.py stays focused on orchestration.
"""

from __future__ import annotations

# ──────────────────────────────────────────────
# Tools exposed to Ollama (OpenAI tool-calling format)
# ──────────────────────────────────────────────

OLLAMA_TOOLS = [
    # ── User API: Messaging tools (5) ──
    {
        "type": "function",
        "function": {
            "name": "send_message",
            "description": "Send a message in an Axomind conversation (user API).",
            "parameters": {
                "type": "object",
                "properties": {
                    "content_message": {
                        "type": "string",
                        "description": "Content of the message to send.",
                    },
                    "id_conversation": {
                        "type": "integer",
                        "description": "ID of the conversation to send the message to.",
                    },
                },
                "required": ["content_message", "id_conversation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_conversations",
            "description": "List all Atlas conversations with their recent messages.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pending_invitations",
            "description": "List pending invitations addressed to Atlas.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "accept_invitation",
            "description": "Accept an invitation from a user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sender_user_id": {
                        "type": "integer",
                        "description": "User ID of the invitation sender.",
                    },
                },
                "required": ["sender_user_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "refuse_invitation",
            "description": "Refuse an invitation from a user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sender_user_id": {
                        "type": "integer",
                        "description": "User ID of the invitation sender.",
                    },
                },
                "required": ["sender_user_id"],
            },
        },
    },
    # ── Bot API: Mindmap tools (6) ──
    {
        "type": "function",
        "function": {
            "name": "list_mindmaps",
            "description": "List mindmaps accessible to the bot (metadata only).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_mindmap",
            "description": "Read a mindmap (full metadata + nodes).",
            "parameters": {
                "type": "object",
                "properties": {
                    "id_mindmap": {
                        "type": "integer",
                        "description": "ID of the mindmap to read.",
                    },
                },
                "required": ["id_mindmap"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sync_nodes",
            "description": "Sync mindmap nodes (Redis + dirty flag). WARNING: DESTRUCTIVE — replaces ALL nodes. Always send the COMPLETE node list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id_mindmap": {
                        "type": "integer",
                        "description": "ID of the mindmap.",
                    },
                    "nodes": {
                        "type": "string",
                        "description": "JSON string — complete list of full-format nodes.",
                    },
                },
                "required": ["id_mindmap", "nodes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_nodes",
            "description": "Append nodes to an existing mindmap (simplified format). Non-destructive: reads the mindmap, appends nodes, syncs the full set.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id_mindmap": {
                        "type": "integer",
                        "description": "ID of the mindmap.",
                    },
                    "nodes": {
                        "type": "string",
                        "description": "JSON string — array of simplified nodes [{title, parent, color?, size_box?, ...}].",
                    },
                },
                "required": ["id_mindmap", "nodes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_mindmap",
            "description": "Replace all nodes in a mindmap (simplified format). WARNING: DESTRUCTIVE — removes and replaces all existing nodes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id_mindmap": {
                        "type": "integer",
                        "description": "ID of the mindmap.",
                    },
                    "nodes": {
                        "type": "string",
                        "description": "JSON string — array of simplified nodes. First node must have parent=0 (root).",
                    },
                },
                "required": ["id_mindmap", "nodes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_nodes_style",
            "description": "Update style fields on specific nodes safely. Reads the mindmap, applies targeted changes, syncs the full set.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id_mindmap": {
                        "type": "integer",
                        "description": "ID of the mindmap.",
                    },
                    "style_updates": {
                        "type": "string",
                        "description": "JSON string — {node_indices: [int], size_box?, line_type?, color?, bold?, ...}. Empty node_indices = all nodes.",
                    },
                },
                "required": ["id_mindmap", "style_updates"],
            },
        },
    },
    # ── Bot API: Messenger tools (4) ──
    {
        "type": "function",
        "function": {
            "name": "bot_send_message",
            "description": "Send a bot message in a conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content_message": {
                        "type": "string",
                        "description": "Content of the message to send.",
                    },
                    "id_conversation": {
                        "type": "integer",
                        "description": "ID of the conversation (0 = broadcast to all assigned conversations).",
                    },
                },
                "required": ["content_message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bot_get_messages",
            "description": "Read bot messages in a conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id_conversation": {
                        "type": "integer",
                        "description": "ID of the conversation.",
                    },
                },
                "required": ["id_conversation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bot_update_message",
            "description": "Update an existing bot message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "update_message_id": {
                        "type": "integer",
                        "description": "ID of the message to update.",
                    },
                    "content_message": {
                        "type": "string",
                        "description": "New message content.",
                    },
                },
                "required": ["update_message_id", "content_message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bot_delete_message",
            "description": "Delete a bot message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "delete_message_id": {
                        "type": "integer",
                        "description": "ID of the message to delete.",
                    },
                },
                "required": ["delete_message_id"],
            },
        },
    },
    # ── Bot API: Planning / Activity tools (5) ──
    {
        "type": "function",
        "function": {
            "name": "list_activities",
            "description": "List activities assigned to the bot (metadata only).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_activity",
            "description": "Read a specific activity (full metadata).",
            "parameters": {
                "type": "object",
                "properties": {
                    "id_activity": {
                        "type": "integer",
                        "description": "ID of the activity.",
                    },
                },
                "required": ["id_activity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_assignment",
            "description": "Assign time slots to an activity.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id_activity": {
                        "type": "integer",
                        "description": "ID of the activity.",
                    },
                    "planning_list": {
                        "type": "string",
                        "description": "JSON string — list of slots to create.",
                    },
                    "recursive_group": {
                        "type": "string",
                        "description": "JSON string — recursive group configuration.",
                    },
                },
                "required": ["id_activity", "planning_list", "recursive_group"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_assignment",
            "description": "Update an existing assignment group.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id_activity": {
                        "type": "integer",
                        "description": "ID of the activity.",
                    },
                    "update_assignement_id": {
                        "type": "integer",
                        "description": "ID of the group to update.",
                    },
                    "planning_list": {
                        "type": "string",
                        "description": "JSON string — new slot list.",
                    },
                    "recursive_group": {
                        "type": "string",
                        "description": "JSON string — new recursive group configuration.",
                    },
                },
                "required": ["id_activity", "update_assignement_id", "planning_list", "recursive_group"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_assignment",
            "description": "Delete an assignment group.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id_activity": {
                        "type": "integer",
                        "description": "ID of the activity.",
                    },
                    "delete_recursive_group_slot": {
                        "type": "integer",
                        "description": "ID of the group to delete.",
                    },
                },
                "required": ["id_activity", "delete_recursive_group_slot"],
            },
        },
    },
]