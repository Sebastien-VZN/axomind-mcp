"""File reader for mindmap injection — extension-based dispatch.

Reads files and converts their content to Quill Delta JSON strings
suitable for the mindmap node 'descriptions' field.

Dispatch by extension:
  - .md / .markdown → markdown_to_quill_delta(content)
  - .txt → plain text Quill Delta: [{"insert": "content\\n"}]
  - .docx, .pdf, .xlsx, .zip, .gz, images, binaries → None (empty description)
  - Unknown extensions → None

Limits:
  - Files larger than 500 KB return None (too large for a mindmap description).
  - Encoding fallback: utf-8 → latin-1 → ignore errors.
  - Empty files return [{"insert": "\\n"}] (empty Quill document).

The dispatch is a simple set-based lookup for easy extension — add new
handlers (docx, pdf) later without touching existing code.
"""

import json
import os

from axomind_mcp.tools.md_to_quill_delta import markdown_to_quill_delta

# Maximum file size to read (500 KB).
_MAX_FILE_SIZE = 500 * 1024

# Extensions handled by the markdown converter.
_MD_EXTENSIONS = {".md", ".markdown"}

# Extensions handled as plain text.
_TXT_EXTENSIONS = {".txt"}

# Extensions that are recognized but return None (binary/complex formats).
# Listed explicitly so the summary can report them.
_IGNORED_EXTENSIONS = {
    ".docx", ".pdf", ".xlsx", ".xls", ".zip", ".gz", ".tar", ".bz2", ".xz",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp", ".ico", ".tiff",
    ".mp3", ".mp4", ".wav", ".ogg", ".flac", ".avi", ".mov", ".mkv", ".webm",
    ".exe", ".dll", ".so", ".bin", ".dat", ".db", ".sqlite", ".db-journal",
    ".pyc", ".class", ".jar", ".war", ".wasm", ".o", ".a",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ".DS_Store",
}


def _read_text(filepath: str) -> str | None:
    """Read file content with encoding fallback (utf-8 -> latin-1 -> ignore).

    Returns None only if the file cannot be read at all (OS-level error).
    """
    for encoding in ("utf-8", "latin-1"):
        try:
            with open(filepath, "r", encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
        except OSError:
            return None
    # Last resort: read with errors="ignore"
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return None


def _wrap_plain_text(content: str) -> str:
    """Wrap plain text content as a Quill Delta JSON string.

    Uses json.dumps for proper escaping of all special characters.
    Returns: [{"insert": "content\\n"}]
    """
    ops = [{"insert": content + "\n"}]
    return json.dumps(ops, ensure_ascii=False)


def read_file_for_quill(filepath: str) -> str | None:
    """Read a file and return its content as a Quill Delta JSON string.

    Dispatch by file extension:
      - .md / .markdown → full markdown-to-Quill conversion
      - .txt → plain text Quill Delta (no markdown parsing)
      - Binary/complex formats (.docx, .pdf, images, etc.) → None
      - Unknown extensions → None

    Returns None if:
      - The file is too large (> 500 KB)
      - The extension is not recognized or is a known binary format
      - Reading fails entirely (OS error)

    Returns [{"insert":"\\n"}] for empty files (empty Quill document).

    The returned string is a valid Quill Delta JSON document. It is
    idempotent: if passed back through markdown_to_quill_delta(), it
    will be returned as-is (detected as already Quill Delta).

    Args:
        filepath: absolute path to the file to read

    Returns:
        Quill Delta JSON string, or None if the file should be skipped.
    """
    # Check file size
    try:
        size = os.path.getsize(filepath)
    except OSError:
        return None

    if size > _MAX_FILE_SIZE:
        return None

    ext = os.path.splitext(filepath)[1].lower()

    # Markdown files → full markdown conversion
    if ext in _MD_EXTENSIONS:
        content = _read_text(filepath)
        if content is None:
            return None
        return markdown_to_quill_delta(content)

    # Plain text files → simple Quill Delta wrap (no markdown parsing)
    if ext in _TXT_EXTENSIONS:
        content = _read_text(filepath)
        if content is None:
            return None
        if not content.strip():
            return '[{"insert":"\\n"}]'
        return _wrap_plain_text(content)

    # Known binary/complex formats → None
    # Unknown extensions → None
    return None


def is_ignored_extension(ext: str) -> bool:
    """Check if an extension is a known binary/complex format."""
    return ext.lower() in _IGNORED_EXTENSIONS