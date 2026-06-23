"""Axomind MCP — Mindmap tools.

Tools for reading, creating, and styling mindmap nodes.
All tools register on the shared FastMCP instance from _common.

WS notification behavior:
    When the bot calls sync_nodes, the PHP backend sends a 'sync_mindmap_nodes'
    WS notification to all participants of the mindmap. However, the bot operates
    as the mindmap owner (rel_id_user), and the WS server does not push
    notifications back to the sender. This means:
    - If the watching user IS the mindmap owner (same user_id as the bot),
      they will NOT receive the real-time WS push. The mindmap is still
      updated in Redis and will sync on next refresh.
    - If the watching user is a participant but NOT the owner, they WILL
      receive the real-time WS notification.
    This is expected behavior (echo suppression), not a bug.
"""

import json

from axomind_mcp._common import DEFAULT_NODE_COLOR, _post, mcp
from axomind_mcp.mindmap.config_layout_mindmap import (
    _build_nodes,
    _calculate_topology_positions,
    _expand_node,
    _validate_simplified_nodes,
)
from axomind_mcp.tools.md_to_quill_delta import markdown_to_quill_delta


# ──────────────────────────────────────────────
# Tools — Mindmap (read)
# ──────────────────────────────────────────────


@mcp.tool()
def list_mindmaps() -> str:
    """List mindmaps where the bot is assigned (metadata only).

    Returns a JSON string with an array of mindmap metadata: id, titre,
    rel_id_user, participants, bots, canvas dimensions, type_mindmap,
    created_datetime, maj_datetime. Does NOT include nodes — use
    get_mindmap to read the full node tree of a specific mindmap.

    Returns:
        JSON string — array of mindmap metadata objects.
    """
    return _post("mindmap", "get_mindmaps")


@mcp.tool()
def get_mindmap(id_mindmap: int) -> str:
    """Read a mindmap (full metadata + all nodes).

    Returns the complete mindmap object with metadata and a 'nodes' array.
    Each node has ~25 fields (position, style, title, descriptions, etc.).

    ⚠️ LARGE RESPONSE: for a mindmap with 60+ nodes and Quill Delta
    descriptions, the response can exceed 2 MB. Only call this when you
    actually need to inspect individual nodes. Do NOT use it to verify
    a previous inject_directory_to_mindmap or replace_mindmap operation —
    those tools return a summary that is sufficient for validation.

    Typical use cases:
    - Reading node structure before add_nodes or update_nodes_style
    - Debugging missing/misplaced nodes
    - Extracting specific node data

    Args:
        id_mindmap: Mindmap ID

    Returns:
        JSON string — {meta: {...}, nodes: [{...}, ...]}.
    """
    return _post("mindmap", "get_mindmap", id_mindmap=id_mindmap)


# ──────────────────────────────────────────────
# Tools — Mindmap (write)
# ──────────────────────────────────────────────


@mcp.tool()
def sync_nodes(id_mindmap: int, nodes: str) -> str:
    """Sync mindmap nodes (Redis only + dirty flag).

    ⚠️ DESTRUCTIVE: replaces ALL nodes. If you send 1 node out of 99,
    the other 98 are deleted. Always send the COMPLETE node list.

    The cron flushDirtyMindmaps handles database persistence.
    This is the same flow used by the Flutter client.

    Args:
        id_mindmap: Mindmap ID
        nodes: JSON string — array of full node objects (advanced use)
    """
    return _post("mindmap", "sync_nodes", id_mindmap=id_mindmap, nodes=nodes)


@mcp.tool()
def add_nodes(id_mindmap: int, nodes: str) -> str:
    """Append nodes to an existing mindmap (simplified format).

    Unlike sync_nodes which replaces everything, add_nodes reads the existing
    mindmap, appends the new nodes, and syncs the full set.

    Simplified node format (JSON string):
    [
        {"title": "Node 1", "parent": 0, "color": "0xFF7A8FF5"},
        {"title": "Node 2", "parent": 1, "color": "0xFFFF6F91"},
        {"title": "Node 3", "parent": 1}
    ]

    Fields:
    - title (required): node title
    - parent (required): order_index of the parent node (0 = root)
    - color (optional): hex color (default: 0xFF7A8FF5)
    - pos_x, pos_y (optional): canvas position (default: 0)
    - size_box (optional): 0=normal, 1=category, 2=root
    - bold, italic, underline (optional): text style
    - line_type (optional): 0=curve, 1=rounded, 2=square
    - line_style (optional): 0=solid, 1=dashed
    - stroke_width, dot_radius, radius, border_size, label_size (optional)
    - icon_id (optional): icon ID
    - active_bg_colors (optional): active background colors
    - descriptions (optional): descriptive text
    - free_links (optional): list of order_index for free links. ONLY use to
      close a cycle (e.g. topology A→B→C→A). Do NOT use in pure tree structures
      (file trees, doc trees, org charts). One free_link per cycle max.
    - spacing_h (optional): horizontal spacing multiplier 0-10 (default: 1). 0=1 cell gap (60px), 1=2 cells (120px), etc.
    - spacing_v (optional): vertical spacing multiplier 0-10 (default: 0)
    - is_write_children (optional): propagate style to children (default: false)

    Auto-positioning: when free_links are present, new nodes are auto-positioned
    using a hierarchical tree layout (retrospective mode). When no free_links,
    positions stay at default (0,0) and the Flutter client handles layout.

    UID and order_index are assigned automatically after existing nodes.
    All other fields are filled with application defaults.

    Args:
        id_mindmap: Mindmap ID
        nodes: JSON string — array of simplified nodes
    """
    try:
        simple_nodes = json.loads(nodes)
        if not isinstance(simple_nodes, list) or not simple_nodes:
            return json.dumps({"error": "nodes must be a non-empty JSON array"})
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON: {e}"})

    # 1. Read existing mindmap
    existing_raw = get_mindmap(id_mindmap)
    try:
        existing = json.loads(existing_raw)
        if "error" in existing:
            return existing_raw
        existing_nodes = existing.get("nodes", [])
    except json.JSONDecodeError:
        return json.dumps({"error": "Failed to parse existing mindmap response"})

    # 2. Find max order_index among existing nodes
    max_oi = 0
    max_uid = 0
    for n in existing_nodes:
        oi = int(n.get("order_index", 0))
        uid = int(n.get("unique_const_id", 0))
        if oi > max_oi:
            max_oi = oi
        if uid > max_uid:
            max_uid = uid

    # 2b. Validate new nodes hierarchy (prevents client crash)
    # In add_nodes, parent can reference existing nodes (0..max_oi) or new nodes
    # (max_oi+1..max_oi+len). New node i (0-indexed) gets order_index = max_oi + i + 1.
    num_new = len(simple_nodes)
    for j, sn in enumerate(simple_nodes):
        node_oi = max_oi + j + 1
        parent = sn.get("parent", 0)
        title = sn.get("title", f"Node {node_oi}")
        if parent == node_oi:
            return json.dumps({"error": f"Validation failed: Node {node_oi} ('{title}'): parent={parent} equals own order_index → self-reference → client CRASH"})
        if parent > node_oi:
            return json.dumps({"error": f"Validation failed: Node {node_oi} ('{title}'): parent={parent} > {node_oi} → forward-reference → invalid"})
        if parent < 0:
            return json.dumps({"error": f"Validation failed: Node {node_oi} ('{title}'): parent={parent} < 0 → invalid"})
        free_links = sn.get("free_links", [])
        if free_links:
            max_possible_oi = max_oi + num_new
            for target in free_links:
                if target == node_oi:
                    return json.dumps({"error": f"Validation failed: Node {node_oi} ('{title}'): free_link targets self ({target}) → invalid"})
                if target < 1 or target > max_possible_oi:
                    return json.dumps({"error": f"Validation failed: Node {node_oi} ('{title}'): free_link target {target} out of range (1-{max_possible_oi}) → invalid"})

    # 2c. Auto-position new nodes if this is a topology (has free_links)
    has_free_links = any(sn.get("free_links") for sn in simple_nodes)
    if has_free_links:
        simple_nodes = _calculate_topology_positions(simple_nodes)

    # 3. Expand new nodes with style options
    next_uid = max_uid + 1
    next_oi = max_oi + 1
    new_nodes = []
    for sn in simple_nodes:
        new_nodes.append(
            _expand_node(
                uid=next_uid,
                order_index=next_oi,
                parent_order_index=sn.get("parent", 0),
                title=sn.get("title", f"Node {next_oi}"),
                color=sn.get("color", DEFAULT_NODE_COLOR),
                pos_x=str(sn.get("pos_x", "0")),
                pos_y=str(sn.get("pos_y", "0")),
                size_box=sn.get("size_box", 0),
                bold=sn.get("bold", False),
                italic=sn.get("italic", False),
                underline=sn.get("underline", False),
                line_type=sn.get("line_type", 0),
                line_style=sn.get("line_style", 0),
                stroke_width=sn.get("stroke_width", 2.5),
                dot_radius=sn.get("dot_radius", 6),
                radius=sn.get("radius", 5),
                border_size=sn.get("border_size", 2),
                label_size=sn.get("label_size", 12),
                icon_id=sn.get("icon_id", 0),
                active_bg_colors=sn.get("active_bg_colors", False),
                descriptions=markdown_to_quill_delta(sn.get("descriptions", "")) if sn.get("descriptions") else "",
                free_links=sn.get("free_links"),
                spacing_h=sn.get("spacing_h", 1),
                spacing_v=sn.get("spacing_v", 0),
                is_write_children=sn.get("is_write_children", False),
                is_manual_position=sn.get("is_manual_position"),
            )
        )
        next_uid += 1
        next_oi += 1

    # 4. Merge and sync
    all_nodes = existing_nodes + new_nodes
    return sync_nodes(id_mindmap, json.dumps(all_nodes, ensure_ascii=False))


@mcp.tool()
def replace_mindmap(id_mindmap: int, nodes: str) -> str:
    """Replace all nodes in a mindmap (simplified format).

    Removes existing nodes and replaces them with the new set.
    The first node must have parent=0 (it becomes the root).

    Simplified format (JSON string):
    [
        {"title": "Root", "parent": 0, "color": "0xFFF0BA6D", "size_box": 2},
        {"title": "Category A", "parent": 1, "color": "0xFF7A8FF5", "size_box": 1},
        {"title": "Item 1", "parent": 2, "color": "0xFF7A8FF5"},
        {"title": "Item 2", "parent": 2}
    ]

    Fields:
    - title (required): node title
    - parent (required): order_index of the parent (0 = root, 1 = first node)
    - color (optional): hex color (default: 0xFF7A8FF5)
    - pos_x, pos_y (optional): canvas position (default: 0)
    - size_box (optional): 0=normal, 1=category, 2=root (default: 0)
    - bold, italic, underline (optional): text style
    - line_type (optional): 0=curve, 1=rounded, 2=square
    - line_style (optional): 0=solid, 1=dashed
    - stroke_width, dot_radius, radius, border_size, label_size (optional)
    - icon_id (optional): icon ID
    - active_bg_colors (optional): active background colors
    - descriptions (optional): descriptive text
    - free_links (optional): list of order_index for free links. ONLY use to
      close a cycle (e.g. topology A→B→C→A). Do NOT use in pure tree structures
      (file trees, doc trees, org charts). One free_link per cycle max.
    - spacing_h (optional): horizontal spacing multiplier 0-10 (default: 1). 0=1 cell gap (60px), 1=2 cells (120px), etc.
    - spacing_v (optional): vertical spacing multiplier 0-10 (default: 0)
    - is_write_children (optional): propagate style to children (default: false)

    Auto-positioning: when free_links are present, nodes are auto-positioned
    using a hierarchical tree layout (retrospective mode). When no free_links,
    positions stay at default (0,0) and the Flutter client handles layout.

    UID and order_index are assigned automatically (1, 2, 3...).
    All other fields are filled with default values.

    Args:
        id_mindmap: Mindmap ID
        nodes: JSON string — array of simplified nodes
    """
    try:
        simple_nodes = json.loads(nodes)
        if not isinstance(simple_nodes, list) or not simple_nodes:
            return json.dumps({"error": "nodes must be a non-empty JSON array"})
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON: {e}"})

    # Validate hierarchy before any expansion (prevents client crash)
    error = _validate_simplified_nodes(simple_nodes)
    if error:
        return json.dumps({"error": f"Validation failed: {error}"})

    # Auto-position nodes if this is a topology (has free_links)
    # Detects free_links → applies hierarchical tree layout (retrospective mode)
    has_free_links = any(sn.get("free_links") for sn in simple_nodes)
    if has_free_links:
        simple_nodes = _calculate_topology_positions(simple_nodes)

    # Expand simplified nodes to full format
    full_nodes = _build_nodes(simple_nodes)
    return sync_nodes(id_mindmap, json.dumps(full_nodes, ensure_ascii=False))


@mcp.tool()
def update_nodes_style(id_mindmap: int, style_updates: str) -> str:
    """Update style fields on specific nodes without losing existing data.

    This is the SAFE way to modify node style — it reads the full mindmap,
    applies targeted changes, and syncs everything back. Never use sync_nodes
    with a partial node list (it deletes everything not sent).

    style_updates is a JSON string:
    {
        "node_indices": [1, 2, 3],  // order_index of nodes to update (empty = all)
        "size_box": 0,               // optional: 0=normal(180×60), 1=category(180×120), 2=root(180×180), 3-11=larger paliers
        "line_type": 1,             // optional: 0=curve, 1=rounded, 2=square
        "line_style": 0,            // optional: 0=solid, 1=dashed
        "spacing_h": 2,             // optional: horizontal spacing multiplier (0-10)
        "spacing_v": 0,             // optional: vertical spacing multiplier (0-10)
        "color": "0xFF7A8FF5",      // optional: hex color
        "bold": true,               // optional
        "italic": false,            // optional
        "underline": false,         // optional
        "stroke_width": 2.5,        // optional
        "dot_radius": 6,            // optional
        "radius": 5,                // optional
        "border_size": 2,           // optional
        "label_size": 12,           // optional
        "icon_id": 0,               // optional
        "active_bg_colors": false,  // optional
        "is_write_children": true,  // optional: propagate style to children
    }

    Only provided fields are updated — others remain untouched.
    If node_indices is empty, the update applies to ALL nodes.

    Args:
        id_mindmap: Mindmap ID
        style_updates: JSON string with node_indices + fields to update
    """
    try:
        updates = json.loads(style_updates)
        if not isinstance(updates, dict):
            return json.dumps({"error": "style_updates must be a JSON object"})
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON: {e}"})

    node_indices = updates.get("node_indices", [])

    # Map AI-friendly names to Flutter JSON field names
    field_map = {
        "size_box": "index_size_box_node",
        "line_type": "type_node_connection",
        "line_style": "type_line_selector",
        "spacing_h": "spacing_nodes_horizontal",
        "spacing_v": "spacing_nodes_vertical",
        "bold": "bold_text",
        "italic": "italic_text",
        "underline": "underline_text",
        "is_write_children": "is_write_children",
        "color": "color",
        "stroke_width": "stroke_width",
        "dot_radius": "dot_radius",
        "radius": "radius",
        "border_size": "border_size",
        "label_size": "label_size",
        "icon_id": "icon_id",
        "active_bg_colors": "active_bg_colors",
    }

    # Build the list of fields to update (only those provided in style_updates)
    updates_to_apply = {}
    for ai_name, flutter_name in field_map.items():
        if ai_name in updates:
            value = updates[ai_name]
            # Validate size_box range (0-11 = 12 paliers in ConfigTreeManager)
            if ai_name == "size_box":
                value = int(value)
                if not (0 <= value <= 11):
                    return json.dumps({"error": f"size_box must be 0-11, got {value}"})
            updates_to_apply[flutter_name] = value

    if not updates_to_apply:
        return json.dumps({"error": "No valid style fields provided in style_updates"})

    # 1. Read existing mindmap
    existing_raw = get_mindmap(id_mindmap)
    try:
        existing = json.loads(existing_raw)
        if "error" in existing:
            return existing_raw
        existing_nodes = existing.get("nodes", [])
    except json.JSONDecodeError:
        return json.dumps({"error": "Failed to parse existing mindmap response"})

    if not existing_nodes:
        return json.dumps({"error": "Mindmap has no nodes to update"})

    # 2. Determine target nodes
    if node_indices:
        target_set = set(int(idx) for idx in node_indices)
    else:
        target_set = set(int(n.get("order_index", 0)) for n in existing_nodes)

    # 3. Apply targeted updates to matching nodes
    updated_count = 0
    for node in existing_nodes:
        oi = int(node.get("order_index", 0))
        if oi in target_set:
            node.update(updates_to_apply)
            updated_count += 1

    if updated_count == 0:
        return json.dumps({"error": f"No nodes matched node_indices: {node_indices}"})

    # 4. Sync ALL nodes back
    sync_result = sync_nodes(id_mindmap, json.dumps(existing_nodes, ensure_ascii=False))

    # 5. Return sync response with update summary
    try:
        result = json.loads(sync_result)
        if isinstance(result, dict):
            result["nodes_updated"] = updated_count
        return json.dumps(result, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return sync_result