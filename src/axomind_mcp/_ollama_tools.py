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
    # ── Bot API: Mindmap summary tools (2) — compact views for context safety ──
    {
        "type": "function",
        "function": {
            "name": "get_mindmap_summary",
            "description": (
                "Read a compact summary of a mindmap — node count, titles, structure, "
                "and whether each node has a description. Does NOT return full node data, "
                "descriptions, positions, or styles. Use this when you need to know how "
                "many nodes exist or what the structure looks like, without loading the "
                "full (potentially huge) mindmap data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "id_mindmap": {
                        "type": "integer",
                        "description": "ID of the mindmap to summarize.",
                    },
                },
                "required": ["id_mindmap"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_node_description",
            "description": (
                "Read the description of a single node in a mindmap by its order_index. "
                "Returns the description text (Quill Delta JSON) for that specific node. "
                "Use this after get_mindmap_summary to read the content of a specific node "
                "without loading the entire mindmap. The description is capped at ~4 KB."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "id_mindmap": {
                        "type": "integer",
                        "description": "ID of the mindmap.",
                    },
                    "order_index": {
                        "type": "integer",
                        "description": "Order index of the node to read (1-based).",
                    },
                },
                "required": ["id_mindmap", "order_index"],
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
            "description": "List all activities assigned to the bot. Returns activity IDs, titles, and participant user IDs. Use this first to find activity IDs before calling get_activity or verify_assignment.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_activity",
            "description": "Read a specific activity's full metadata, including assignment groups (recursive groups with title, date range, active weekdays) and all time slots (slot_id, day_of_year, user_id, start_time, end_time). Use this to inspect what slots are assigned to which users.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id_activity": {
                        "type": "integer",
                        "description": "ID of the activity (from list_activities).",
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
            "description": "Delete an assignment group and all its time slots.",
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
    # ── Bot API: Planning helpers (3) — human-friendly wrappers ──
    {
        "type": "function",
        "function": {
            "name": "verify_assignment",
            "description": "Verify and inspect all assignments for an activity. Returns a readable telemetry report with: activity info (id, title, participants), per-group details (group_id, title, type, date range, active weekdays), per-slot details (slot_id, day_of_year, user_id, start/end times), and consistency checks. Use this to read the planning of an activity in a human-readable format.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id_activity": {
                        "type": "integer",
                        "description": "ID of the activity to verify (from list_activities).",
                    },
                },
                "required": ["id_activity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_planning",
            "description": "Read ALL time slots for a given year. This is the ONLY tool that returns actual slot data (start_time, end_time, dates, user assignments). get_activity and verify_assignment do NOT return slot data — use read_planning instead. Returns a report organized by activity, with per-group details (title, date range, active weekdays) and per-slot details (date, day_of_year, user_id, start/end times). Pass id_activity=0 to get all activities, or a specific activity ID to filter.",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {
                        "type": "integer",
                        "description": "Year to read (e.g. 2026). Returns all slots for that year.",
                    },
                    "id_activity": {
                        "type": "integer",
                        "description": "Optional: filter to a specific activity. 0 = all activities (default).",
                    },
                },
                "required": ["year"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_assignment",
            "description": "Create a planning assignment with human-friendly parameters. Builds the JSON payloads internally — just provide dates (YYYY-MM-DD), times (hour/minute integers), and weekday names. Single-day: start_date == end_date, weekdays omitted. Recursive: start_date < end_date, weekdays specifies active days (monday, tuesday, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "id_activity": {
                        "type": "integer",
                        "description": "ID of the activity (from list_activities).",
                    },
                    "user_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "List of user IDs to assign (from activity participants).",
                    },
                    "titre": {
                        "type": "string",
                        "description": "Assignment title (e.g. \"Morning shift\").",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Start date in YYYY-MM-DD format (e.g. \"2026-06-23\").",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date in YYYY-MM-DD format. For single-day, use same as start_date.",
                    },
                    "start_hour": {
                        "type": "integer",
                        "description": "Start hour 0-23 (e.g. 8 for 08:00).",
                    },
                    "start_minute": {
                        "type": "integer",
                        "description": "Start minute 0-59 (e.g. 0).",
                    },
                    "end_hour": {
                        "type": "integer",
                        "description": "End hour 0-23 (e.g. 14 for 14:00).",
                    },
                    "end_minute": {
                        "type": "integer",
                        "description": "End minute 0-59 (e.g. 0).",
                    },
                    "weekdays": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Active weekday names for recursive mode. Case-insensitive: monday/mon, tuesday/tue, etc. Omit for single-day.",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes text.",
                    },
                },
                "required": ["id_activity", "user_ids", "titre", "start_date", "end_date", "start_hour", "start_minute", "end_hour", "end_minute"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "modify_assignment",
            "description": "Modify an existing assignment group with human-friendly parameters. Replaces the group definition and all its time slots. Uses the same parameters as create_assignment but requires group_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id_activity": {
                        "type": "integer",
                        "description": "ID of the activity.",
                    },
                    "group_id": {
                        "type": "integer",
                        "description": "Existing group ID to update (from get_activity or verify_assignment).",
                    },
                    "user_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "List of user IDs to assign.",
                    },
                    "titre": {
                        "type": "string",
                        "description": "Assignment title.",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Start date in YYYY-MM-DD format.",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date in YYYY-MM-DD format (same as start_date for single-day).",
                    },
                    "start_hour": {
                        "type": "integer",
                        "description": "Start hour 0-23.",
                    },
                    "start_minute": {
                        "type": "integer",
                        "description": "Start minute 0-59.",
                    },
                    "end_hour": {
                        "type": "integer",
                        "description": "End hour 0-23.",
                    },
                    "end_minute": {
                        "type": "integer",
                        "description": "End minute 0-59.",
                    },
                    "weekdays": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Active weekday names for recursive mode. Omit for single-day.",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes text.",
                    },
                },
                "required": ["id_activity", "group_id", "user_ids", "titre", "start_date", "end_date", "start_hour", "start_minute", "end_hour", "end_minute"],
            },
        },
    },
]