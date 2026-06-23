"""Axomind MCP — Mindmap layout constants and node expansion helpers.

Mirror of ConfigTreeManager (Flutter client). All values are multiples
of the grid cell (60px). Used by _mindmap.py for node expansion.

Design rules (enforced in code or documented in docstrings):
1. Positions must be strict multiples of GRID_CELL (60px). The Flutter client
   snaps to grid — non-multiple values get rounded, causing visual drift.
2. is_manual_position=true on all positioned nodes so the client preserves
   them. Without it, the client recalculates layout and overwrites positions.
3. Auto-positioning uses a hierarchical tree layout (retrospective mode only):
   depth → X, leaves spread → Y, parents centered on children (median).
4. AI-provided pos_x/pos_y are NEVER overwritten — only is_manual_position
   is set to true. The MCP calculates positions only when the AI doesn't
   provide them.
5. Auto-positioning triggers ONLY when free_links are present. Pure tree
   structures (no free_links) are left at (0,0) — the client handles layout.
6. free_links close a CYCLE (e.g. topology A→B→C→A). Do NOT use in pure tree
   hierarchies (file trees, doc trees, org charts). One free_link per cycle.
7. Never use free_links between parent and child already connected via
   the hierarchy — it's redundant, the lines draw automatically.
"""

import json

from axomind_mcp._common import DEFAULT_NODE_COLOR, _NODE_DEFAULTS
from axomind_mcp.tools.md_to_quill_delta import markdown_to_quill_delta

# ──────────────────────────────────────────────
# Layout constants — mirror of ConfigTreeManager (Flutter client)
# All values are multiples of the grid cell (60px).
# ──────────────────────────────────────────────

GRID_CELL = 60  # defaultNodeWidth/3 = defaultNodeHeight
DEFAULT_NODE_WIDTH = 180  # 3 × GRID_CELL
DEFAULT_NODE_HEIGHT = 60  # 1 × GRID_CELL

# spacing_h / spacing_v are multipliers (0-10), NOT raw pixels.
# Layout formula (calcul_layout_tree.dart line 748):
#   spacing = spacingNodesHorizontal + 1
#   result = valSize + (spacing * treeIndentStep)   # treeIndentStep = GRID_CELL = 60
# So spacing_h=0 → 1×60=60px gap, spacing_h=1 → 2×60=120px, etc.
SPACING_MIN = 0
SPACING_MAX = 10

# TypeMindMap (config_tree_mindmap_manager.dart line 208)
TYPE_MINDMAP_RETROSPECTIVE = 0  # horizontal, children right of root
TYPE_MINDMAP_ORGANIGRAMME = 1    # vertical top-down
TYPE_MINDMAP_LIST = 2            # indented vertical list
TYPE_MINDMAP_MINDMAP = 3         # radial, children both sides

# Layout params per type (changePositionNodes)
LAYOUT_PARAMS = {
    TYPE_MINDMAP_RETROSPECTIVE: {"spaceHorizontalLevel": 180, "spaceVerticalMin": 60, "marginH": 240, "marginV": 180},
    TYPE_MINDMAP_ORGANIGRAMME: {"spaceHorizontalLevel": 180, "spaceVerticalMin": 60, "marginH": 180, "marginV": 180},
    TYPE_MINDMAP_LIST: {"treeIndentStep": 60, "spaceVerticalMin": 60, "marginH": 180, "marginV": 180},
    TYPE_MINDMAP_MINDMAP: {"spaceHorizontalLevel": 180, "spaceVerticalMin": 60, "marginH": 240, "marginV": 240},
}

# TypeNodeConnection (line 247) — controls parent→child line style
TYPE_NODE_CONNECTION_CURVE = 0    # bezier (default)
TYPE_NODE_CONNECTION_ROUNDED = 1  # rounded corners
TYPE_NODE_CONNECTION_SQUARE = 2   # square angles

# TypeLine (line 253) — stroke style
TYPE_LINE_SOLID = 0   # solid (default)
TYPE_LINE_DASHED = 1  # dashed

# Slider ranges from form_edit_node.dart
LABEL_SIZE_MIN = 10
LABEL_SIZE_MAX = 60
ICON_SIZE_MIN = 10
ICON_SIZE_MAX = 140
STROKE_WIDTH_MIN = 1
STROKE_WIDTH_MAX = 6
DOT_RADIUS_MIN = 1
DOT_RADIUS_MAX = 10
BORDER_SIZE_MIN = 0
BORDER_SIZE_MAX = 5
RADIUS_MIN = 0
RADIUS_MAX = 5


# ──────────────────────────────────────────────
# Helpers — expansion of simplified nodes
# ──────────────────────────────────────────────


def _expand_node(
    uid: int,
    order_index: int,
    parent_order_index: int,
    title: str,
    color: str = DEFAULT_NODE_COLOR,
    pos_x: str = "0",
    pos_y: str = "0",
    size_box: int = 0,
    # Style options (all optional, override defaults)
    bold: bool = False,
    italic: bool = False,
    underline: bool = False,
    line_type: int = 0,
    line_style: int = 0,
    stroke_width: float = 2.5,
    dot_radius: float = 6,
    radius: int = 5,
    border_size: int = 2,
    label_size: float = 12,
    icon_id: int = 0,
    active_bg_colors: bool = False,
    descriptions: str = "",
    free_links: list | None = None,
    spacing_h: int = 1,
    spacing_v: int = 0,
    is_write_children: bool = False,
    is_manual_position: bool | None = None,
) -> dict:
    """Build a full node from essential fields + optional style overrides.

    All other fields (~25) are filled with default values expected by the
    Flutter application.

    Args:
        uid: unique_const_id
        order_index: position in the hierarchy
        parent_order_index: order_index of the parent (0 = root)
        title: node title
        color: hex color (e.g. "0xFF7A8FF5")
        pos_x, pos_y: canvas position
        size_box: 0=normal, 1=category, 2=root
        bold: bold text
        italic: italic text
        underline: underlined text
        line_type: connection style (0=curve, 1=rounded, 2=square)
        line_style: line stroke style (0=solid, 1=dashed)
        stroke_width: line thickness
        dot_radius: endpoint dot radius
        radius: corner radius
        border_size: border thickness
        label_size: text size
        icon_id: icon ID
        active_bg_colors: active background colors
        descriptions: descriptive text
        free_links: list of order_index for free links. ONLY use to close a
          cycle (e.g. topology A→B→C→A). Do NOT use in pure tree structures.
          One free_link per cycle max. Never between parent-child (redundant).
        spacing_h: horizontal spacing multiplier (0-10)
        spacing_v: vertical spacing multiplier (0-10)
        is_write_children: propagate style to children
    """
    # Defaults first, then specific values take priority
    node = dict(_NODE_DEFAULTS)
    node.update({
        "unique_const_id": str(uid),
        "order_index": str(order_index),
        "parent_order_index": str(parent_order_index),
        "index_size_box_node": size_box,
        "title": title,
        "color": color,
        "pos_x": pos_x,
        "pos_y": pos_y,
        "is_manual_position": "true" if (is_manual_position if is_manual_position is not None else size_box >= 2) else "false",
        # Style overrides
        "bold_text": bold,
        "italic_text": italic,
        "underline_text": underline,
        "type_node_connection": line_type,
        "type_line_selector": line_style,
        "stroke_width": stroke_width,
        "dot_radius": dot_radius,
        "radius": radius,
        "border_size": border_size,
        "label_size": label_size,
        "icon_id": icon_id,
        "active_bg_colors": active_bg_colors,
        "descriptions": descriptions,
        "spacing_nodes_horizontal": spacing_h,
        "spacing_nodes_vertical": spacing_v,
        "is_write_children": is_write_children,
    })
    if free_links is not None:
        node["free_link_order_index"] = json.dumps(free_links)
    return node


# ──────────────────────────────────────────────
# Layout constants — retrospective type (mirror ConfigTreeManager)
# ──────────────────────────────────────────────

# Retrospective: horizontal layout, tree grows right
ROOT_X = GRID_CELL * 4       # 240px = margingCanvasHorizontal (retrospective)
ROOT_Y = GRID_CELL * 8       # 480px = vertical center for canvas ~1200px
# X step per depth level = node width (180) + spaceHorizontalLevel (180) - node width = 180
# But client uses: depthNext = node.posX + node.width + gap
# gap = spaceHorizontalLevel (180) + treeIndentStep - defaultNodeWidth = 180 + 60 - 180 = 60
# So depthNext = posX + 180 + 60 = posX + 240 → 4 cells per level
DEPTH_STEP_X = GRID_CELL * 4  # 240px per depth level
# Y step between siblings = node height (60) + spaceVerticalMin (60) = 120
SIBLING_STEP_Y = GRID_CELL * 2  # 120px between siblings


def _calculate_topology_positions(simple_nodes: list) -> list:
    """Auto-position nodes using a hierarchical tree layout (retrospective mode).

    Mirrors the Flutter client's _computeCenteredPositions algorithm:
    - Horizontal layout (retrospective): tree grows left → right.
    - X = ROOT_X + depth × DEPTH_STEP_X (depth from root).
    - Y = spread leaves vertically, parents centered on children (median).
    - All positions are strict multiples of GRID_CELL (60px).
    - All positioned nodes get is_manual_position = True.

    Rules for AI-provided positions:
    - If the AI provides pos_x/pos_y for a node → respect them, do NOT overwrite.
      Only set is_manual_position = True so the Flutter client preserves them.

    Trigger: auto-positioning activates ONLY when at least one node has
    free_links. Pure tree structures (no free_links) are left at default
    positions (0,0) — the Flutter client handles their layout automatically.

    Layout constants (mirror ConfigTreeManager, retrospective type):
    - ROOT_X = 240  (margingCanvasHorizontal)
    - ROOT_Y = 480  (vertical center for ~1200px canvas)
    - DEPTH_STEP_X = 240  (4×60: node width 180 + gap 60)
    - SIBLING_STEP_Y = 120  (2×60: node height 60 + spaceVerticalMin 60)

    Args:
        simple_nodes: list of simplified node dicts (will be mutated in-place)

    Returns:
        The same list with pos_x, pos_y, and is_manual_position set.
    """
    n = len(simple_nodes)
    if n == 0:
        return simple_nodes

    # 1. Build children mapping (parent_order_index → [list indices])
    children: dict[int, list[int]] = {}
    for i, node in enumerate(simple_nodes):
        parent_oi = node.get("parent", 0)
        children.setdefault(parent_oi, []).append(i)

    # 2. Compute depth for each node (BFS from root at index 0)
    depth: dict[int, int] = {0: 0}
    queue = [0]
    while queue:
        idx = queue.pop(0)
        node_oi = idx + 1  # order_index is 1-based
        for child_idx in children.get(node_oi, []):
            depth[child_idx] = depth[idx] + 1
            queue.append(child_idx)

    # 3. Collect leaves in DFS order (left-to-right traversal)
    leaves: list[int] = []
    def _collect_leaves(idx: int) -> None:
        node_oi = idx + 1
        childs = children.get(node_oi, [])
        if not childs:
            leaves.append(idx)
            return
        for child_idx in childs:
            _collect_leaves(child_idx)
    _collect_leaves(0)

    # 4. Assign Y to leaves sequentially (spread vertically)
    y_pos: dict[int, int] = {}
    for i, leaf_idx in enumerate(leaves):
        y_pos[leaf_idx] = ROOT_Y + i * SIBLING_STEP_Y

    # 5. Assign Y to internal nodes bottom-up (median of children)
    def _compute_y(idx: int) -> int:
        if idx in y_pos:
            return y_pos[idx]
        node_oi = idx + 1
        child_indices = children.get(node_oi, [])
        if not child_indices:
            y_pos[idx] = ROOT_Y
            return y_pos[idx]
        child_ys = sorted(_compute_y(c) for c in child_indices)
        # Lower median — always a multiple of 60 since children are
        median_idx = len(child_ys) // 2
        y_pos[idx] = child_ys[median_idx]
        return y_pos[idx]

    for i in range(n):
        _compute_y(i)

    # 6. Assign positions
    for i, node in enumerate(simple_nodes):
        # Check if the AI already provided non-zero positions
        pos_x = str(node.get("pos_x", "0"))
        pos_y = str(node.get("pos_y", "0"))
        has_ai_positions = pos_x != "0" or pos_y != "0"

        if has_ai_positions:
            # Respect AI-provided positions — do NOT overwrite
            node["is_manual_position"] = True
            continue

        node["pos_x"] = str(ROOT_X + depth[i] * DEPTH_STEP_X)
        node["pos_y"] = str(y_pos[i])
        node["is_manual_position"] = True

    return simple_nodes


def _validate_simplified_nodes(simple_nodes: list) -> str | None:
    """Validate simplified nodes before expansion to prevent Flutter client crashes.

    Rules (order_index is assigned sequentially: 1, 2, 3...):
    1. For node at position i (1-indexed), parent must be in [0, i-1].
       parent == i → self-reference → infinite loop → CRASH
       parent > i → forward-reference → invalid
    2. parent must be >= 0.
    3. free_links cannot target the node itself.
    4. free_links must target valid order_index (1..len(nodes)).

    Design guidance for the AI (not enforced, but critical for correct results):
    - Free links close a CYCLE (e.g. topology A→B→C→A). They are NOT for
      connecting nodes in a pure tree hierarchy (file structures, doc trees,
      org charts). Adding a free_link in a tree-only structure creates
      unnecessary visual clutter.
    - One free_link per cycle, linking the last node back to an ancestor.
    - Never use free_links between parent and child that are already
      connected via the hierarchy — it's redundant.

    Returns error message string if validation fails, None if valid.
    """
    n = len(simple_nodes)
    for i, node in enumerate(simple_nodes, start=1):
        parent = node.get("parent", 0)
        title = node.get("title", f"Node {i}")

        if parent == i:
            return f"Node {i} ('{title}'): parent={parent} equals own order_index → self-reference → client CRASH"
        if parent > i:
            return f"Node {i} ('{title}'): parent={parent} > {i} → forward-reference to non-existent node → invalid"
        if parent < 0:
            return f"Node {i} ('{title}'): parent={parent} < 0 → invalid"

        free_links = node.get("free_links", [])
        if free_links:
            for target in free_links:
                if target == i:
                    return f"Node {i} ('{title}'): free_link targets self ({target}) → invalid"
                if target < 1 or target > n:
                    return f"Node {i} ('{title}'): free_link target {target} out of range (1-{n}) → invalid"

    return None


def _build_nodes(simple_nodes: list) -> list:
    """Transform a list of simplified nodes into full nodes.

    Simplified format (all style fields are optional):
    {
        "title": str,           # required
        "parent": int,           # required (order_index of parent, 0=root)
        "color": str,            # optional, hex (default: 0xFF7A8FF5)
        "pos_x": str,            # optional (default: "0")
        "pos_y": str,            # optional (default: "0")
        "size_box": int,         # optional (0=normal, 1=category, 2=root)
        "bold": bool,            # optional, bold text
        "italic": bool,          # optional, italic text
        "underline": bool,       # optional, underlined text
        "line_type": int,        # optional (0=curve, 1=rounded, 2=square)
        "line_style": int,       # optional (0=solid, 1=dashed)
        "stroke_width": float,   # optional, line thickness
        "dot_radius": float,     # optional, endpoint dot radius
        "radius": int,           # optional, corner radius
        "border_size": int,      # optional, border thickness
        "label_size": float,     # optional, text size
        "icon_id": int,           # optional, icon ID
        "active_bg_colors": bool,# optional, active background colors
        "descriptions": str,     # optional, descriptive text
        "free_links": [int, ...] # optional, free links. ONLY to close a cycle
                                  # (e.g. A→B→C→A). NOT for pure trees. One per cycle.
        "spacing_h": int,        # optional, horizontal spacing multiplier (0-10, default: 1)
        "spacing_v": int,        # optional, vertical spacing multiplier (0-10)
        "is_write_children": bool # optional, propagate style to children
    }

    UID and order_index are assigned sequentially starting from 1.
    """
    full_nodes = []
    for i, sn in enumerate(simple_nodes, start=1):
        full_nodes.append(
            _expand_node(
                uid=i,
                order_index=i,
                parent_order_index=sn.get("parent", 0),
                title=sn.get("title", f"Node {i}"),
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
    return full_nodes