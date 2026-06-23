"""Tests for the Markdown to Quill Delta converter."""

import json

import pytest

from axomind_mcp.tools.md_to_quill_delta import is_quill_delta, markdown_to_quill_delta


class TestMarkdownToQuillDelta:
    """Test the markdown_to_quill_delta converter."""

    def _parse(self, result: str) -> list:
        """Parse the JSON string result into a list of ops."""
        return json.loads(result)

    def test_empty_string_returns_empty_doc(self):
        """Empty string should return the empty-document Delta."""
        result = markdown_to_quill_delta("")
        assert result == '[{"insert":"\\n"}]'

    def test_none_or_whitespace_returns_empty_doc(self):
        """None or whitespace-only should return the empty-document Delta."""
        assert markdown_to_quill_delta("") == '[{"insert":"\\n"}]'
        assert markdown_to_quill_delta("   ") == '[{"insert":"\\n"}]'
        assert markdown_to_quill_delta("\n\n") == '[{"insert":"\\n"}]'

    def test_plain_text(self):
        """Plain text without any Markdown formatting."""
        result = markdown_to_quill_delta("Hello world")
        ops = self._parse(result)
        # Should have: {"insert": "Hello world"}, {"insert": "\n"}
        assert any(op.get("insert") == "Hello world" for op in ops)
        assert ops[-1].get("insert") == "\n"

    def test_header_h1(self):
        """H1 header: # Title"""
        result = markdown_to_quill_delta("# Title")
        ops = self._parse(result)
        assert any(op.get("insert") == "Title" for op in ops)
        assert any(op.get("attributes", {}).get("header") == 1 for op in ops)

    def test_header_h2(self):
        """H2 header: ## Subtitle"""
        result = markdown_to_quill_delta("## Subtitle")
        ops = self._parse(result)
        assert any(op.get("insert") == "Subtitle" for op in ops)
        assert any(op.get("attributes", {}).get("header") == 2 for op in ops)

    def test_header_h3(self):
        """H3 header: ### Section"""
        result = markdown_to_quill_delta("### Section")
        ops = self._parse(result)
        assert any(op.get("insert") == "Section" for op in ops)
        assert any(op.get("attributes", {}).get("header") == 3 for op in ops)

    def test_bold(self):
        """Bold: **text** or __text__"""
        result = markdown_to_quill_delta("Some **bold** text")
        ops = self._parse(result)
        bold_ops = [op for op in ops if op.get("attributes", {}).get("bold") is True]
        assert len(bold_ops) == 1
        assert bold_ops[0]["insert"] == "bold"

    def test_bold_underscore(self):
        """Bold: __text__"""
        result = markdown_to_quill_delta("Some __bold__ text")
        ops = self._parse(result)
        bold_ops = [op for op in ops if op.get("attributes", {}).get("bold") is True]
        assert len(bold_ops) == 1
        assert bold_ops[0]["insert"] == "bold"

    def test_italic(self):
        """Italic: *text*"""
        result = markdown_to_quill_delta("Some *italic* text")
        ops = self._parse(result)
        italic_ops = [op for op in ops if op.get("attributes", {}).get("italic") is True]
        assert len(italic_ops) == 1
        assert italic_ops[0]["insert"] == "italic"

    def test_strikethrough_removed(self):
        """Strikethrough: ~~text~~ — tildes stripped, text kept as plain text."""
        result = markdown_to_quill_delta("~~deleted~~ text")
        ops = self._parse(result)
        strike_ops = [op for op in ops if op.get("attributes", {}).get("strike") is True]
        assert len(strike_ops) == 0
        full_text = "".join(op.get("insert", "") for op in ops if isinstance(op.get("insert"), str))
        assert "deleted" in full_text

    def test_inline_code_removed(self):
        """Inline code: `code` — backticks stripped, text kept as plain text."""
        result = markdown_to_quill_delta("Use printf function")
        ops = self._parse(result)
        code_ops = [op for op in ops if op.get("attributes", {}).get("code") is True]
        assert len(code_ops) == 0
        full_text = "".join(op.get("insert", "") for op in ops if isinstance(op.get("insert"), str))
        assert "printf" in full_text

    def test_link(self):
        """Link: [text](url) — rendered as bold (no link attribute to avoid white highlight in Flutter)."""
        result = markdown_to_quill_delta("Click [here](https://example.com) now")
        ops = self._parse(result)
        bold_ops = [op for op in ops if op.get("attributes", {}).get("bold") is True]
        assert len(bold_ops) == 1
        assert bold_ops[0]["insert"] == "here"

    def test_bullet_list(self):
        """Bullet list: - item"""
        result = markdown_to_quill_delta("- item 1\n- item 2")
        ops = self._parse(result)
        bullet_ops = [op for op in ops if op.get("attributes", {}).get("list") == "bullet"]
        assert len(bullet_ops) == 2

    def test_ordered_list(self):
        """Ordered list: 1. item"""
        result = markdown_to_quill_delta("1. first\n2. second")
        ops = self._parse(result)
        ordered_ops = [op for op in ops if op.get("attributes", {}).get("list") == "ordered"]
        assert len(ordered_ops) == 2

    def test_blockquote(self):
        """Blockquote: > text"""
        result = markdown_to_quill_delta("> quoted text")
        ops = self._parse(result)
        quote_ops = [op for op in ops if op.get("attributes", {}).get("blockquote") is True]
        assert len(quote_ops) == 1

    def test_thematic_break_removed(self):
        """Thematic break: --- — removed entirely, no embed."""
        result = markdown_to_quill_delta("Before\n---\nAfter")
        ops = self._parse(result)
        # Should NOT contain "---" as an embed dict or plain text
        divider_ops = [op for op in ops if isinstance(op.get("insert"), dict)]
        assert len(divider_ops) == 0
        text_ops = [op for op in ops if isinstance(op.get("insert"), str) and op["insert"] == "---"]
        assert len(text_ops) == 0
        # Text before and after should still be present
        full_text = "".join(op.get("insert", "") for op in ops if isinstance(op.get("insert"), str))
        assert "Before" in full_text
        assert "After" in full_text

    def test_code_fence_removed(self):
        """Code fences (``` and ```dart etc) — removed entirely."""
        md = "Some text\n```dart\nprint(hello)\n```\nMore text"
        result = markdown_to_quill_delta(md)
        ops = self._parse(result)
        # Should NOT contain ``` or print(hello)
        full_text = "".join(op.get("insert", "") for op in ops if isinstance(op.get("insert"), str))
        assert "```" not in full_text
        assert "print(hello)" not in full_text
        # Text before and after should still be present
        assert "Some text" in full_text
        assert "More text" in full_text

    def test_multi_line_document(self):
        """Multiple lines with mixed formatting."""
        md = "# Title\n\nSome **bold** and *italic* text.\n\n- item 1\n- item 2"
        result = markdown_to_quill_delta(md)
        ops = self._parse(result)
        assert len(ops) >= 5
        # Verify header
        assert any(op.get("attributes", {}).get("header") == 1 for op in ops)
        # Verify bold
        assert any(op.get("attributes", {}).get("bold") is True for op in ops)
        # Verify italic
        assert any(op.get("attributes", {}).get("italic") is True for op in ops)
        # Verify bullet list
        bullet_ops = [op for op in ops if op.get("attributes", {}).get("list") == "bullet"]
        assert len(bullet_ops) == 2

    def test_idempotent_quill_delta(self):
        """If input is already Quill Delta JSON, return as-is."""
        existing = '[{"insert":"hello\\n"}]'
        result = markdown_to_quill_delta(existing)
        assert result == existing

    def test_idempotent_complex_delta(self):
        """Complex Quill Delta should be returned as-is."""
        existing = json.dumps([
            {"insert": "Title", "attributes": {"bold": True}},
            {"insert": "\n", "attributes": {"header": 1}},
            {"insert": "Body text\n"},
        ])
        result = markdown_to_quill_delta(existing)
        assert result == existing

    def test_mixed_bold_and_link(self):
        """Bold text inside a link should not double-process. Links render as bold."""
        md = "**[bold link](https://example.com)**"
        result = markdown_to_quill_delta(md)
        ops = self._parse(result)
        bold_ops = [op for op in ops if op.get("attributes", {}).get("bold") is True]
        assert len(bold_ops) >= 1

    def test_special_characters(self):
        """Special characters in text should be preserved (except quotes/backticks which are stripped)."""
        md = "Price: 100€ — OK"
        result = markdown_to_quill_delta(md)
        ops = self._parse(result)
        full_text = "".join(op.get("insert", "") for op in ops if isinstance(op.get("insert"), str))
        assert "100€" in full_text
        assert "—" in full_text

    def test_code_with_special_chars_removed(self):
        """Code blocks with special characters — backticks stripped, text kept."""
        result = markdown_to_quill_delta("Use array in code")
        ops = self._parse(result)
        code_ops = [op for op in ops if op.get("attributes", {}).get("code") is True]
        assert len(code_ops) == 0
        full_text = "".join(op.get("insert", "") for op in ops if isinstance(op.get("insert"), str))
        assert "array" in full_text

    def test_double_quotes_stripped(self):
        """Double quotes should be stripped from text."""
        result = markdown_to_quill_delta('Text with "quotes" inside')
        ops = self._parse(result)
        full_text = "".join(op.get("insert", "") for op in ops if isinstance(op.get("insert"), str))
        assert '"' not in full_text
        assert "Text with" in full_text
        assert "quotes" in full_text
        assert "inside" in full_text

    def test_single_quotes_stripped(self):
        """Single quotes should be stripped from text."""
        result = markdown_to_quill_delta("Text with don't worry")
        ops = self._parse(result)
        full_text = "".join(op.get("insert", "") for op in ops if isinstance(op.get("insert"), str))
        assert "'" not in full_text
        assert "dont" in full_text
        assert "worry" in full_text

    def test_backticks_stripped(self):
        """Backticks should be stripped from text."""
        result = markdown_to_quill_delta("Use `printf` in code")
        ops = self._parse(result)
        full_text = "".join(op.get("insert", "") for op in ops if isinstance(op.get("insert"), str))
        assert "`" not in full_text
        assert "printf" in full_text
        assert "code" in full_text

    def test_no_embed_dicts_in_output(self):
        """No operation should have a dict as insert value (no embeds)."""
        md = "# Title\n\nSome **bold** text.\n\n- item 1\n\n```\ncode block\n```\n\n---\n\n> quote"
        result = markdown_to_quill_delta(md)
        ops = self._parse(result)
        embed_ops = [op for op in ops if isinstance(op.get("insert"), dict)]
        assert len(embed_ops) == 0

    def test_no_problematic_attributes(self):
        """No link, code, strike, or background attributes should be present."""
        md = "# Title\n\n**bold** *italic* ~~strike~~ `code` [link](http://x.com)\n\n> quote\n\n---\n\n```dart\ncode\n```"
        result = markdown_to_quill_delta(md)
        ops = self._parse(result)
        for op in ops:
            attrs = op.get("attributes", {})
            assert "link" not in attrs, f"link attr found in op: {op}"
            assert "code" not in attrs, f"code attr found in op: {op}"
            assert "strike" not in attrs, f"strike attr found in op: {op}"
            assert "background" not in attrs, f"background attr found in op: {op}"


class TestIsQuillDelta:
    """Test the is_quill_delta detector."""

    def test_empty_string(self):
        assert not is_quill_delta("")

    def test_plain_text(self):
        assert not is_quill_delta("Hello world")

    def test_quill_delta(self):
        assert is_quill_delta('[{"insert":"hello\\n"}]')

    def test_complex_quill_delta(self):
        delta = json.dumps([
            {"insert": "text", "attributes": {"bold": True}},
            {"insert": "\n"},
        ])
        assert is_quill_delta(delta)

    def test_markdown(self):
        assert not is_quill_delta("# Header\n\nSome text")