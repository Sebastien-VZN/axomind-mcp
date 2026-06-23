"""Markdown to Quill Delta converter.

Converts plain text or Markdown-formatted text into the Quill Delta JSON
format expected by the Flutter client's AdvancedTextEditor / TextAreaViewerStatic.

The Quill Delta format is a JSON array of operations:
    [{"insert": "text", "attributes": {...}}, ...]

Each "insert" operation contributes text to the document. The "attributes"
map applies inline or line-level formatting (bold, italic, headers, lists, etc.).
A trailing "\\n" in an insert marks the end of a line/block.

Supported Markdown features (subset relevant to Axomind documentation):
- # H1, ## H2, ### H3  → header attribute (1, 2, 3)
- **bold** / __bold__  → bold attribute
- *italic* / _italic_  → italic attribute
- [text](url)          → bold attribute (link text rendered bold, no link attribute)
- - item / * item      → list: bullet
- 1. item              → list: ordered
- > quote              → blockquote attribute
- Plain paragraphs     → plain insert + \\n
- Empty lines          → just \\n

Sanitization: the following are stripped from all text content to prevent
Quill rendering issues:
- Code fences (``` and variants) — removed entirely
- Thematic breaks (---, ***, ___) — removed entirely
- Backticks (`) — removed
- Double quotes (") — removed
- Single quotes (') — removed
- Inline code (`code`) — backticks removed, text kept as plain text
- Strikethrough (~~text~~) — tildes removed, text kept as plain text

If the input is already a Quill Delta JSON string (starts with [{"insert"),
it is returned as-is — the conversion is idempotent.
"""

from __future__ import annotations

import json
import re
from typing import Any


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────


def markdown_to_quill_delta(text: str) -> str:
    """Convert plain text or Markdown into a Quill Delta JSON string.

    If the input is already a Quill Delta JSON array, it is returned as-is.
    If the input is empty, returns an empty-document Delta: [{"insert":"\\n"}].

    Args:
        text: plain text, Markdown-formatted text, or existing Quill Delta JSON.

    Returns:
        A JSON string representing a Quill Delta document.
    """
    if not text or not text.strip():
        return '[{"insert":"\\n"}]'

    # Idempotent: if already Quill Delta JSON, return as-is
    stripped = text.strip()
    if stripped.startswith("[{") and '"insert"' in stripped:
        return text

    ops: list[dict[str, Any]] = _markdown_to_ops(stripped)
    if not ops:
        return '[{"insert":"\\n"}]'

    return json.dumps(ops, ensure_ascii=False)


def is_quill_delta(text: str) -> bool:
    """Check if a string is already a Quill Delta JSON document."""
    if not text:
        return False
    stripped = text.strip()
    return stripped.startswith("[{") and '"insert"' in stripped


# ──────────────────────────────────────────────
# Text sanitization
# ──────────────────────────────────────────────


def _sanitize_text(text: str) -> str:
    """Remove characters that cause Quill rendering issues.

    Strips: backticks, double quotes, single quotes, tildes.
    These characters confuse the Quill Delta parser or cause silent rendering failures.
    """
    # Remove backticks (inline code markers)
    text = text.replace("`", "")
    # Remove double quotes
    text = text.replace('"', "")
    # Remove single quotes
    text = text.replace("'", "")
    # Remove tildes (strikethrough markers)
    text = text.replace("~~", "")
    # Remove box-drawing characters (U+2500-U+257F) used in file tree diagrams
    text = re.sub(r"[\u2500-\u257F]", "", text)
    # NOTE: square brackets are NOT removed here — they are needed by _emit_inline_ops
    # to detect Markdown links [text](url). They are stripped from residual plain text
    # inside _emit_inline_ops after link extraction.
    return text


# ──────────────────────────────────────────────
# File tree detection (box-drawing characters)
# ──────────────────────────────────────────────

# Box-drawing characters: U+2500–U+257F (├ │ └ ─ ┌ ┐ ┘ ┤ etc.)
_RE_BOX_DRAWING = re.compile(r"[\u2500-\u257F]")


def _is_file_tree_line(line: str) -> bool:
    """Check if a line is part of a file tree diagram (uses box-drawing chars)."""
    return bool(_RE_BOX_DRAWING.search(line))


def _emit_file_tree_ops(ops: list[dict[str, Any]], tree_lines: list[str]) -> None:
    """Convert file tree diagram lines into Quill Delta ops.

    Keeps box-drawing characters (├ │ └ ─) in the text.
    Splits file name and inline comment (after 2+ spaces or ' # ').
    Sanitizes only problematic chars (backticks, quotes, brackets) but NOT box-drawing.
    """
    for raw_line in tree_lines:
        # Find the branch character (├── or └──)
        branch_match = re.search(r"[├└]──", raw_line)
        if branch_match:
            # Keep the full line with box chars, just sanitize problematic chars
            content = raw_line.rstrip()
        else:
            # Root line or line without branch char
            content = raw_line.rstrip()

        if not content.strip():
            continue

        # Sanitize only problematic chars, preserve box-drawing
        sanitized = content
        sanitized = sanitized.replace("`", "").replace('"', "").replace("'", "")
        sanitized = sanitized.replace("[", "").replace("]", "")
        sanitized = sanitized.replace("~~", "")

        ops.append({"insert": sanitized})
        ops.append({"insert": "\n"})


# ──────────────────────────────────────────────
# Core conversion logic
# ──────────────────────────────────────────────


def _markdown_to_ops(md: str) -> list[dict[str, Any]]:
    """Parse Markdown text into a list of Quill Delta operations."""
    ops: list[dict[str, Any]] = []
    lines = md.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines — they become bare \n inserts
        if not stripped:
            ops.append({"insert": "\n"})
            i += 1
            continue

        # Code fences: ``` or ```bash or ```dart etc
        if stripped.startswith("```"):
            # Check if the content inside the fence is a file tree (box-drawing chars)
            # If so, convert it to bullet list ops instead of skipping
            fence_lines: list[str] = []
            i += 1
            while i < len(lines):
                if lines[i].strip().startswith("```"):
                    i += 1
                    break
                fence_lines.append(lines[i])
                i += 1

            if fence_lines and any(_is_file_tree_line(fl) for fl in fence_lines):
                # File tree inside code fence — convert to plain text with indentation
                _emit_file_tree_ops(ops, fence_lines)
            # else: non-tree code block — skip content entirely
            continue

        # Thematic break: --- or *** or ___ — skip entirely
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            i += 1
            continue

        # File tree detection: consecutive lines containing box-drawing characters
        # (├ │ └ ─ etc, U+2500-U+257F). Convert to plain text with indentation.
        if _is_file_tree_line(line):
            tree_lines: list[str] = [line]
            j = i + 1
            while j < len(lines) and _is_file_tree_line(lines[j]):
                tree_lines.append(lines[j])
                j += 1
            _emit_file_tree_ops(ops, tree_lines)
            i = j
            continue

        # Headers: # H1, ## H2, ### H3 (and beyond)
        header_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if header_match:
            level = len(header_match.group(1))
            content = _sanitize_text(header_match.group(2).strip())
            _emit_inline_ops(ops, content)
            ops.append({"insert": "\n", "attributes": {"header": level}})
            i += 1
            continue

        # Blockquote: > text
        if stripped.startswith(">"):
            quote_content = _sanitize_text(stripped[1:].strip())
            _emit_inline_ops(ops, quote_content)
            ops.append({"insert": "\n", "attributes": {"blockquote": True}})
            i += 1
            continue

        # Ordered list: 1. item, 2. item, etc.
        ordered_match = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if ordered_match:
            content = _sanitize_text(ordered_match.group(2).strip())
            _emit_inline_ops(ops, content)
            ops.append({"insert": "\n", "attributes": {"list": "ordered"}})
            i += 1
            continue

        # Bullet list: - item or * item
        bullet_match = re.match(r"^[-*]\s+(.+)$", stripped)
        if bullet_match:
            content = _sanitize_text(bullet_match.group(1).strip())
            _emit_inline_ops(ops, content)
            ops.append({"insert": "\n", "attributes": {"list": "bullet"}})
            i += 1
            continue

        # Regular paragraph line
        sanitized = _sanitize_text(stripped)
        _emit_inline_ops(ops, sanitized)
        ops.append({"insert": "\n"})
        i += 1

    return ops


# ──────────────────────────────────────────────
# Inline formatting parser
# ──────────────────────────────────────────────

# Only bold and italic are handled as inline formatting.
# Links are rendered as bold (no link attribute to avoid white highlight in Flutter).
# Code, strikethrough have been removed — characters are stripped by _sanitize_text.

# Bold: **text** or __text__
# __ must be at word boundary (preceded by space/start, followed by non-space)
_RE_BOLD = re.compile(r"\*\*(.+?)\*\*|(?<![\w])__(?![\s])(.+?)(?<![\s])__(?![\w])")
# Italic: *text* or _text_ (but not inside ** or __, and not mid-word)
# _ must be at word boundary (preceded by space/start, followed by non-space)
_RE_ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<![\w])_(?![\s])(.+?)(?<![\s])_(?![\w])")
# Links: [text](url)
_RE_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _emit_inline_ops(ops: list[dict[str, Any]], text: str) -> None:
    """Parse a line of text with inline Markdown formatting into Quill ops.

    Handles: links (rendered as bold), bold, italic. Unformatted segments
    are emitted as plain {"insert": "text"} ops.
    """
    if not text:
        return

    # Collect all matches with their positions
    tokens: list[tuple[int, int, str, list[dict[str, Any]]]] = []

    for match in _RE_LINK.finditer(text):
        # Sanitize the link text
        link_text = _sanitize_text(match.group(1))
        if link_text:
            tokens.append((
                match.start(),
                match.end(),
                "link",
                [{"insert": link_text, "attributes": {"bold": True}}],
            ))

    for match in _RE_BOLD.finditer(text):
        if _overlaps_existing(match, tokens):
            continue
        content = match.group(1) or match.group(2) or ""
        # Content is already sanitized at the line level, but bold markers
        # capture inner text that might not have been sanitized yet
        content = _sanitize_text(content)
        if content:
            tokens.append((
                match.start(),
                match.end(),
                "bold",
                [{"insert": content, "attributes": {"bold": True}}],
            ))

    for match in _RE_ITALIC.finditer(text):
        if _overlaps_existing(match, tokens):
            continue
        content = match.group(1) or match.group(2) or ""
        content = _sanitize_text(content)
        if content:
            tokens.append((
                match.start(),
                match.end(),
                "italic",
                [{"insert": content, "attributes": {"italic": True}}],
            ))

    # Sort by start position
    tokens.sort(key=lambda t: t[0])

    # Emit: plain text before first token, then alternating token/plain
    cursor = 0
    for start, end, _kind, token_ops in tokens:
        if start > cursor:
            # Plain text segment — strip brackets (residual from non-link [text])
            plain = text[cursor:start].replace("[", "").replace("]", "")
            if plain:
                ops.append({"insert": plain})
        ops.extend(token_ops)
        cursor = end

    # Trailing plain text
    if cursor < len(text):
        plain = text[cursor:].replace("[", "").replace("]", "")
        if plain:
            ops.append({"insert": plain})


def _overlaps_existing(match: re.Match[str], tokens: list[tuple[int, int, str, list[dict[str, Any]]]]) -> bool:
    """Check if a match overlaps with an already-collected token."""
    for start, end, _kind, _ops in tokens:
        if match.start() < end and match.end() > start:
            return True
    return False