"""Axomind MCP — Directory tree to mindmap converter.

Scans a directory and builds a simplified JSON array ready for replace_mindmap
or add_nodes. The order_index assignment is automatic (1-based, sequential),
so the AI never has to manually track parent indices — zero risk of off-by-one.

Two tools are provided:
  - tree_to_mindmap: full tree → JSON nodes for replace_mindmap/add_nodes
  - tree_scope: compact telemetry (title, size, type only) — no file content,
    designed to keep the AI focused without saturating its context window.

Pure local computation — no HTTP call to bot_api.php.
"""

import json
import os
from typing import Any

from axomind_mcp._common import mcp
from axomind_mcp.tools._file_reader import _IGNORED_EXTENSIONS, read_file_for_quill
from axomind_mcp.mindmap._mindmap import sync_nodes
from axomind_mcp.mindmap.config_layout_mindmap import _build_nodes, _validate_simplified_nodes

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────

# Skip these entries when scanning (hidden files, VCS, build artifacts).
_SKIP_NAMES = {
    ".git",
    ".github",
    ".gitignore",
    ".gitattributes",
    ".vscode",
    ".idea",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    ".env",
    "env",
    "node_modules",
    ".DS_Store",
    "Thumbs.db",
}

# Color for directory nodes (categories).
_DIR_COLOR = "0xFF7A8FF5"
# Color for file nodes (leaves).
_FILE_COLOR = "0xFFF0BA6D"
# Color for the root node.
_ROOT_COLOR = "0xFFF0BA6D"

# Maximum depth to prevent runaway scans on huge trees.
_MAX_DEPTH = 15
# Maximum total nodes (safety cap).
_MAX_NODES = 500


def _should_skip(name: str, extra_skip: set[str] | None = None) -> bool:
    """Check if a file/dir name should be skipped during scanning."""
    # Skip all dotfiles/dotdirs (hidden entries: .git, .gitignore, .hidden, .DS_Store, etc.)
    if name.startswith("."):
        return True
    if name in _SKIP_NAMES:
        return True
    if extra_skip and name in extra_skip:
        return True
    return False


def _scan_dir(
    path: str,
    nodes: list[dict[str, Any]],
    parent_oi: int,
    depth: int,
    extra_skip: set[str] | None = None,
    path_map: dict[int, str] | None = None,
) -> None:
    """Recursively scan a directory and append nodes to the list.

    Args:
        path: absolute path to scan
        nodes: list to append nodes to (mutated in place)
        parent_oi: order_index of the parent node
        depth: current depth (0 = root's children)
        extra_skip: additional names to skip
        path_map: if provided, maps each node's order_index to its absolute filepath
    """
    if depth > _MAX_DEPTH or len(nodes) >= _MAX_NODES:
        return

    try:
        entries = sorted(os.listdir(path))
    except PermissionError:
        return

    # Separate dirs and files — dirs first (they become categories), then files.
    dirs = []
    files = []
    for entry in entries:
        if _should_skip(entry, extra_skip):
            continue
        full = os.path.join(path, entry)
        if os.path.isdir(full):
            dirs.append(entry)
        else:
            files.append(entry)

    for name in dirs:
        if len(nodes) >= _MAX_NODES:
            return
        full = os.path.join(path, name)
        oi = len(nodes) + 1  # 1-based order_index = position in array + 1
        nodes.append({
            "title": name,
            "parent": parent_oi,
            "size_box": 1,
            "color": _DIR_COLOR,
        })
        if path_map is not None:
            path_map[oi] = full
        _scan_dir(full, nodes, oi, depth + 1, extra_skip, path_map)

    for name in files:
        if len(nodes) >= _MAX_NODES:
            return
        full = os.path.join(path, name)
        oi = len(nodes) + 1
        nodes.append({
            "title": name,
            "parent": parent_oi,
            "color": _FILE_COLOR,
        })
        if path_map is not None:
            path_map[oi] = full


def build_tree_nodes(
    root_path: str,
    root_title: str | None = None,
    skip_names: set[str] | None = None,
    path_map: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    """Build a simplified node array from a directory tree.

    Args:
        root_path: absolute path to the directory to scan
        root_title: title for the root node (defaults to the directory name)
        skip_names: additional names to skip (merged with default _SKIP_NAMES)
        path_map: if provided, maps each node's order_index to its absolute filepath

    Returns:
        List of simplified nodes ready for replace_mindmap or add_nodes.
        The first node is the root (parent=0, size_box=2).
        All order_index values are implicit (1-based position in the list).
    """
    if not os.path.isdir(root_path):
        raise NotADirectoryError(f"Not a directory: {root_path}")

    title = root_title or os.path.basename(os.path.normpath(root_path))
    nodes: list[dict[str, Any]] = [{
        "title": title,
        "parent": 0,
        "size_box": 2,
        "color": _ROOT_COLOR,
        "line_type": 1,
    }]
    if path_map is not None:
        path_map[1] = root_path
    _scan_dir(root_path, nodes, 1, 0, skip_names, path_map)

    return nodes


# ──────────────────────────────────────────────
# Scope — compact telemetry (no file content)
# ──────────────────────────────────────────────


def _human_size(size_bytes: int) -> str:
    """Convert byte count to human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f}GB"


def _scan_scope(
    path: str,
    entries: list[dict[str, Any]],
    parent_oi: int,
    depth: int,
    max_depth: int,
) -> None:
    """Recursively scan a directory and append compact scope entries.

    Each entry is: {title, type, size, oi, parent, depth}
    - type: "dir" or "file"
    - size: human-readable (for files) or item count (for dirs)
    - oi: 1-based order_index
    - parent: order_index of parent
    - depth: nesting level (0 = root's children)
    """
    if depth > max_depth:
        return

    try:
        names = sorted(os.listdir(path))
    except PermissionError:
        return

    dirs = []
    files = []
    for name in names:
        if _should_skip(name):
            continue
        full = os.path.join(path, name)
        if os.path.isdir(full):
            dirs.append(name)
        else:
            files.append(name)

    for name in dirs:
        full = os.path.join(path, name)
        oi = len(entries) + 1
        # Count immediate children for a quick sense of dir size
        try:
            child_count = len([
                n for n in os.listdir(full)
                if not _should_skip(n)
            ])
        except PermissionError:
            child_count = 0

        entries.append({
            "title": name,
            "type": "dir",
            "items": child_count,
            "oi": oi,
            "parent": parent_oi,
            "depth": depth,
        })
        _scan_scope(full, entries, oi, depth + 1, max_depth)

    for name in files:
        full = os.path.join(path, name)
        try:
            size = os.path.getsize(full)
            size_str = _human_size(size)
        except OSError:
            size_str = "?"

        entries.append({
            "title": name,
            "type": "file",
            "size": size_str,
            "oi": len(entries) + 1,
            "parent": parent_oi,
            "depth": depth,
        })


def build_tree_scope(
    root_path: str,
    root_title: str | None = None,
    max_depth: int = 10,
) -> list[dict[str, Any]]:
    """Build a compact scope array from a directory tree.

    Unlike build_tree_nodes, this returns telemetry only — no mindmap node
    fields, no file content. Just: title, type, size/items, oi, parent, depth.
    Designed to give the AI a lightweight overview for piloting decisions.
    """
    if not os.path.isdir(root_path):
        raise NotADirectoryError(f"Not a directory: {root_path}")

    title = root_title or os.path.basename(os.path.normpath(root_path))
    entries: list[dict[str, Any]] = [{
        "title": title,
        "type": "root",
        "oi": 1,
        "parent": 0,
        "depth": -1,
    }]
    _scan_scope(root_path, entries, 1, 0, max_depth)

    return entries


# ──────────────────────────────────────────────
# MCP Tools
# ──────────────────────────────────────────────


@mcp.tool()
def tree_to_mindmap(
    root_path: str,
    root_title: str = "",
) -> str:
    """Scan a directory tree and return a JSON array of simplified mindmap nodes.

    The returned JSON is ready to use with replace_mindmap or add_nodes.
    Order_index is implicit (1-based position in the array). Parent values
    are pre-computed — no manual index tracking needed.

    Directories become category nodes (size_box=1), files become leaf nodes.
    Hidden files, VCS dirs (.git, .github, __pycache__, node_modules, etc.)
    are skipped automatically.

    Args:
        root_path: absolute path to the directory to scan
        root_title: title for the root node (empty = use directory name)

    Returns:
        JSON string — array of simplified nodes ready for replace_mindmap.
    """
    try:
        nodes = build_tree_nodes(root_path, root_title or None)
        return json.dumps(nodes, ensure_ascii=False)
    except (NotADirectoryError, FileNotFoundError) as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"Scan failed: {e}"})


@mcp.tool()
def tree_scope(
    root_path: str,
    root_title: str = "",
    max_depth: int = 10,
) -> str:
    """Scan a directory and return compact telemetry (no file content).

    Returns a JSON array where each entry is:
      {title, type, size, oi, parent, depth}

    - type: "dir", "file", or "root"
    - size: human-readable for files (e.g. "2.3KB"), item count for dirs
    - oi: 1-based order_index (matches what tree_to_mindmap would produce)
    - parent: order_index of the parent node
    - depth: nesting level (0 = root's direct children)

    Use this BEFORE inject_directory_to_mindmap to get a reference count of
    expected nodes (1 root + N dirs + M files). After injection, compare the
    summary's total_nodes with this count to validate — no need to call
    get_mindmap afterwards.

    Does NOT read file content — just names, sizes, and structure.
    Hidden files and VCS dirs are skipped automatically.

    Args:
        root_path: absolute path to the directory to scan
        root_title: title for the root entry (empty = use directory name)
        max_depth: maximum nesting depth to scan (default 10)

    Returns:
        JSON string — array of compact scope entries.
    """
    try:
        entries = build_tree_scope(root_path, root_title or None, max_depth)
        return json.dumps(entries, ensure_ascii=False)
    except (NotADirectoryError, FileNotFoundError) as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"Scan failed: {e}"})


# ──────────────────────────────────────────────
# Tool — inject_directory_to_mindmap
# ──────────────────────────────────────────────


@mcp.tool()
def inject_directory_to_mindmap(
    root_path: str,
    root_title: str = "",
    id_mindmap: int = 0,
) -> str:
    """Scan a directory, read file contents, and inject everything into a mindmap.

    This is a one-shot tool: it scans the directory tree, reads each file's
    content, converts it to Quill Delta JSON (for .md/.markdown/.txt files),
    builds the full node hierarchy, and syncs it to the mindmap via sync_nodes.

    The AI does NOT need to manipulate JSON — everything happens internally.

    RECOMMENDED WORKFLOW:
    1. Call tree_scope on the same path to get a reference count.
    2. Call inject_directory_to_mindmap with the same path + id_mindmap.
    3. Compare the returned summary (total_nodes, descriptions_filled) with
       the tree_scope count. If they match and errors is empty, the injection
       is validated — do NOT call get_mindmap to re-verify.

    File handling by extension:
      - .md / .markdown → content converted via markdown_to_quill_delta()
      - .txt → content wrapped as plain text Quill Delta
      - .docx, .pdf, .xlsx, images, binaries, etc. → node created, description empty
      - Unknown extensions → node created, description empty
      - Files > 500 KB → node created, description empty (too large)

    The 'descriptions' field on each node is a Quill Delta JSON string.
    Directory nodes (categories) never get descriptions — only file leaves do.

    Args:
        root_path: absolute path to the directory to scan
        root_title: title for the root node (empty = use directory name)
        id_mindmap: target mindmap ID to inject the nodes into

    Returns:
        JSON string with a summary:
        {"status": "success", "total_nodes": N, "descriptions_filled": N,
         "files_ignored": N, "total_desc_size_kb": N, "errors": [],
         "ignored_formats": [".docx", ".pdf", ...]}
    """
    if not id_mindmap:
        return json.dumps({"error": "id_mindmap is required (must be > 0)"})

    try:
        # 1. Build the tree structure with a path map (order_index → filepath)
        path_map: dict[int, str] = {}
        nodes = build_tree_nodes(root_path, root_title or None, path_map=path_map)
    except (NotADirectoryError, FileNotFoundError) as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"Scan failed: {e}"})

    if len(nodes) == 1:
        # Only the root node — empty directory
        try:
            full_nodes = _build_nodes(nodes)
            sync_result = sync_nodes(id_mindmap, json.dumps(full_nodes, ensure_ascii=False))
            _ = json.loads(sync_result)  # validate it's JSON
        except Exception as e:
            return json.dumps({"error": f"sync_nodes failed: {e}"})
        return json.dumps({
            "status": "success",
            "total_nodes": 1,
            "descriptions_filled": 0,
            "files_ignored": 0,
            "total_desc_size_kb": 0.0,
            "errors": [],
            "ignored_formats": [],
        })

    # 2. Read file contents and assign descriptions to file nodes
    descriptions_filled = 0
    files_ignored = 0
    total_desc_size = 0
    errors: list[str] = []
    ignored_formats: set[str] = set()

    for i, node in enumerate(nodes):
        oi = i + 1  # 1-based order_index
        filepath = path_map.get(oi)
        if filepath is None:
            continue  # root or missing path

        # Skip directories (only file leaves get descriptions)
        if os.path.isdir(filepath):
            continue

        ext = os.path.splitext(filepath)[1].lower()

        # Read and convert file content
        desc = read_file_for_quill(filepath)
        if desc is not None:
            node["descriptions"] = desc
            descriptions_filled += 1
            total_desc_size += len(desc)
        else:
            files_ignored += 1
            if ext in _IGNORED_EXTENSIONS:
                ignored_formats.add(ext)

    # 3. Validate hierarchy (no forward references, no self-references)
    error = _validate_simplified_nodes(nodes)
    if error:
        return json.dumps({"error": f"Validation failed: {error}"})

    # 4. Convert to full node format and sync
    try:
        full_nodes = _build_nodes(nodes)
        sync_result = sync_nodes(id_mindmap, json.dumps(full_nodes, ensure_ascii=False))
        # Check if sync returned an error
        try:
            result = json.loads(sync_result)
            if isinstance(result, dict) and "error" in result:
                return json.dumps({"error": f"sync_nodes failed: {result['error']}"})
        except json.JSONDecodeError:
            errors.append("sync_nodes returned non-JSON response")
    except Exception as e:
        return json.dumps({"error": f"sync_nodes failed: {e}"})

    # 5. Return compact summary
    return json.dumps({
        "status": "success",
        "total_nodes": len(nodes),
        "descriptions_filled": descriptions_filled,
        "files_ignored": files_ignored,
        "total_desc_size_kb": round(total_desc_size / 1024, 1),
        "errors": errors,
        "ignored_formats": sorted(ignored_formats),
    }, ensure_ascii=False)