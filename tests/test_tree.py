"""Unit tests for the directory tree to mindmap converter (_tree.py).

Tests the tree scanning, order_index assignment, hierarchy validation,
and the compact scope telemetry mode.
"""

import json
import os
import tempfile

import pytest

from axomind_mcp.tools._tree import build_tree_nodes, build_tree_scope


class TestBuildTreeNodes:
    """Tests for build_tree_nodes — full mindmap node generation."""

    def test_flat_dir(self, tmp_path):
        """A flat directory with 3 files produces 4 nodes (root + 3 leaves)."""
        (tmp_path / "a.md").write_text("content a")
        (tmp_path / "b.md").write_text("content b")
        (tmp_path / "c.txt").write_text("content c")

        nodes = build_tree_nodes(str(tmp_path), "TestRoot")

        assert len(nodes) == 4
        assert nodes[0]["title"] == "TestRoot"
        assert nodes[0]["parent"] == 0
        assert nodes[0]["size_box"] == 2
        # Files are sorted alphabetically
        assert nodes[1]["title"] == "a.md"
        assert nodes[2]["title"] == "b.md"
        assert nodes[3]["title"] == "c.txt"
        # All files are children of root (oi=1)
        assert nodes[1]["parent"] == 1
        assert nodes[2]["parent"] == 1
        assert nodes[3]["parent"] == 1

    def test_nested_dirs(self, tmp_path):
        """Nested directories produce correct parent indices."""
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "file1.md").write_text("x")
        (tmp_path / "top.md").write_text("y")

        nodes = build_tree_nodes(str(tmp_path), "Root")

        # Root=oi1, subdir=oi2 (dir, parent=1), file1.md=oi3 (parent=2), top.md=oi4 (parent=1)
        assert len(nodes) == 4
        assert nodes[0]["title"] == "Root"
        assert nodes[1]["title"] == "subdir"
        assert nodes[1]["parent"] == 1
        assert nodes[1]["size_box"] == 1
        assert nodes[2]["title"] == "file1.md"
        assert nodes[2]["parent"] == 2  # child of subdir
        assert nodes[3]["title"] == "top.md"
        assert nodes[3]["parent"] == 1  # child of root

    def test_dirs_before_files(self, tmp_path):
        """Directories appear before files at each level."""
        (tmp_path / "z_file.md").write_text("z")
        (tmp_path / "a_dir").mkdir()

        nodes = build_tree_nodes(str(tmp_path), "Root")

        # a_dir should come before z_file.md despite 'z' > 'a'
        assert nodes[1]["title"] == "a_dir"
        assert nodes[2]["title"] == "z_file.md"

    def test_skip_hidden_and_vcs(self, tmp_path):
        """Hidden files and VCS directories are skipped."""
        (tmp_path / ".hidden").write_text("x")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("x")
        (tmp_path / "visible.md").write_text("x")

        nodes = build_tree_nodes(str(tmp_path), "Root")

        # Only root + visible.md
        assert len(nodes) == 2
        assert nodes[1]["title"] == "visible.md"

    def test_default_root_title(self, tmp_path):
        """When root_title is None, uses the directory name."""
        (tmp_path / "file.md").write_text("x")
        nodes = build_tree_nodes(str(tmp_path))
        # The root title should be the directory basename
        assert nodes[0]["title"] == os.path.basename(str(tmp_path))

    def test_hierarchy_no_forward_refs(self, tmp_path):
        """No node has a parent >= its own order_index (forward reference)."""
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "b").mkdir()
        (tmp_path / "a" / "b" / "c.md").write_text("x")
        (tmp_path / "a" / "d.md").write_text("y")
        (tmp_path / "e.md").write_text("z")

        nodes = build_tree_nodes(str(tmp_path), "Root")
        for i, node in enumerate(nodes):
            oi = i + 1
            assert node["parent"] < oi, f"Node {oi} has parent={node['parent']} >= {oi}"
            assert node["parent"] >= 0

    def test_not_a_directory(self):
        """Passing a file path raises NotADirectoryError."""
        with pytest.raises(NotADirectoryError):
            build_tree_nodes("/etc/hostname", "Root")

    def test_nonexistent_path(self):
        """Passing a nonexistent path raises NotADirectoryError."""
        with pytest.raises(NotADirectoryError):
            build_tree_nodes("/nonexistent/path/that/does/not/exist", "Root")

    def test_deep_nesting(self, tmp_path):
        """Deep nesting produces correct parent chains."""
        current = tmp_path
        for i in range(5):
            current = current / f"level{i}"
            current.mkdir()
        (current / "leaf.md").write_text("deep")

        nodes = build_tree_nodes(str(tmp_path), "Root")
        # Verify the chain: root → level0 → level1 → ... → level4 → leaf.md
        # Each level should have parent = previous level's oi
        assert len(nodes) == 7  # root + 5 dirs + 1 file
        for i, node in enumerate(nodes):
            oi = i + 1
            assert node["parent"] < oi

    def test_empty_directory(self, tmp_path):
        """An empty directory produces just the root node."""
        nodes = build_tree_nodes(str(tmp_path), "Empty")
        assert len(nodes) == 1
        assert nodes[0]["title"] == "Empty"
        assert nodes[0]["parent"] == 0


class TestBuildTreeScope:
    """Tests for build_tree_scope — compact telemetry mode."""

    def test_scope_basic(self, tmp_path):
        """Scope returns compact entries with type, size, oi, parent, depth."""
        (tmp_path / "file.md").write_text("hello world")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "nested.md").write_text("nested content")

        scope = build_tree_scope(str(tmp_path), "Root")

        assert len(scope) == 4
        assert scope[0]["title"] == "Root"
        assert scope[0]["type"] == "root"

        # Find the file and check it has a size
        file_entry = next(e for e in scope if e["title"] == "file.md")
        assert file_entry["type"] == "file"
        assert "size" in file_entry
        assert "B" in file_entry["size"] or "KB" in file_entry["size"]

        # Find the dir and check it has items count
        dir_entry = next(e for e in scope if e["title"] == "subdir")
        assert dir_entry["type"] == "dir"
        assert "items" in dir_entry
        assert dir_entry["items"] == 1  # one file inside

    def test_scope_oi_matches_nodes(self, tmp_path):
        """Scope order_index values match build_tree_nodes exactly."""
        (tmp_path / "a_dir").mkdir()
        (tmp_path / "a_dir" / "x.md").write_text("x")
        (tmp_path / "b.md").write_text("y")

        nodes = build_tree_nodes(str(tmp_path), "Root")
        scope = build_tree_scope(str(tmp_path), "Root")

        assert len(nodes) == len(scope)
        for i in range(len(nodes)):
            assert nodes[i]["title"] == scope[i]["title"]
            assert nodes[i]["parent"] == scope[i]["parent"]

    def test_scope_no_file_content(self, tmp_path):
        """Scope never includes file content — only title, type, size."""
        secret_content = "THIS IS SECRET CONTENT THAT SHOULD NOT LEAK"
        (tmp_path / "secret.md").write_text(secret_content)

        scope = build_tree_scope(str(tmp_path), "Root")
        scope_json = json.dumps(scope)

        assert secret_content not in scope_json
        assert "THIS IS SECRET" not in scope_json

    def test_scope_max_depth(self, tmp_path):
        """max_depth limits how deep the scan goes."""
        current = tmp_path
        for i in range(5):
            current = current / f"d{i}"
            current.mkdir()
        (current / "deep.md").write_text("deep")

        scope_shallow = build_tree_scope(str(tmp_path), "Root", max_depth=1)
        scope_deep = build_tree_scope(str(tmp_path), "Root", max_depth=10)

        # Shallow scan should have fewer entries
        assert len(scope_shallow) < len(scope_deep)
        # Deep scan should find the leaf
        titles_deep = [e["title"] for e in scope_deep]
        assert "deep.md" in titles_deep

    def test_scope_skip_hidden(self, tmp_path):
        """Scope also skips hidden files and VCS dirs."""
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("x")
        (tmp_path / ".hidden").write_text("x")
        (tmp_path / "visible.md").write_text("x")

        scope = build_tree_scope(str(tmp_path), "Root")
        assert len(scope) == 2  # root + visible.md only


class TestHumanSize:
    """Tests for the _human_size helper."""

    def test_bytes(self):
        from axomind_mcp.tools._tree import _human_size
        assert _human_size(0) == "0B"
        assert _human_size(512) == "512B"
        assert _human_size(1023) == "1023B"

    def test_kilobytes(self):
        from axomind_mcp.tools._tree import _human_size
        assert "KB" in _human_size(1024)
        assert "KB" in _human_size(50000)

    def test_megabytes(self):
        from axomind_mcp.tools._tree import _human_size
        assert "MB" in _human_size(1024 * 1024)
        assert "MB" in _human_size(5 * 1024 * 1024)


class TestReadFileForQuill:
    """Tests for _file_reader.read_file_for_quill — extension-based dispatch."""

    def test_markdown_file(self, tmp_path):
        """A .md file returns Quill Delta JSON with header attributes."""
        from axomind_mcp.tools._file_reader import read_file_for_quill

        f = tmp_path / "test.md"
        f.write_text("# Title\n\nSome paragraph.\n")
        result = read_file_for_quill(str(f))
        assert result is not None
        ops = json.loads(result)
        assert isinstance(ops, list)
        # Should contain a header attribute
        assert any(op.get("attributes", {}).get("header") == 1 for op in ops)

    def test_markdown_file_extension_variant(self, tmp_path):
        """A .markdown file is handled the same as .md."""
        from axomind_mcp.tools._file_reader import read_file_for_quill

        f = tmp_path / "test.markdown"
        f.write_text("# Hello\n")
        result = read_file_for_quill(str(f))
        assert result is not None
        ops = json.loads(result)
        assert any(op.get("attributes", {}).get("header") == 1 for op in ops)

    def test_txt_file(self, tmp_path):
        """A .txt file returns plain text Quill Delta (no markdown parsing)."""
        from axomind_mcp.tools._file_reader import read_file_for_quill

        f = tmp_path / "notes.txt"
        f.write_text("Just plain text.\nNo markdown here.")
        result = read_file_for_quill(str(f))
        assert result is not None
        ops = json.loads(result)
        assert isinstance(ops, list)
        # Plain text → single insert with the full content + \n
        assert len(ops) == 1
        assert "Just plain text" in ops[0]["insert"]
        assert ops[0]["insert"].endswith("\n")

    def test_empty_file(self, tmp_path):
        """An empty file returns the empty Quill document."""
        from axomind_mcp.tools._file_reader import read_file_for_quill

        f = tmp_path / "empty.md"
        f.write_text("")
        result = read_file_for_quill(str(f))
        assert result is not None
        assert result == '[{"insert":"\\n"}]'

    def test_empty_txt_file(self, tmp_path):
        """An empty .txt file returns the empty Quill document."""
        from axomind_mcp.tools._file_reader import read_file_for_quill

        f = tmp_path / "empty.txt"
        f.write_text("")
        result = read_file_for_quill(str(f))
        assert result is not None
        assert result == '[{"insert":"\\n"}]'

    def test_docx_returns_none(self, tmp_path):
        """A .docx file returns None (binary format, not supported)."""
        from axomind_mcp.tools._file_reader import read_file_for_quill

        f = tmp_path / "doc.docx"
        f.write_bytes(b"fake docx content")
        result = read_file_for_quill(str(f))
        assert result is None

    def test_pdf_returns_none(self, tmp_path):
        """A .pdf file returns None."""
        from axomind_mcp.tools._file_reader import read_file_for_quill

        f = tmp_path / "doc.pdf"
        f.write_bytes(b"fake pdf content")
        result = read_file_for_quill(str(f))
        assert result is None

    def test_unknown_extension_returns_none(self, tmp_path):
        """An unrecognized extension returns None."""
        from axomind_mcp.tools._file_reader import read_file_for_quill

        f = tmp_path / "data.xyz"
        f.write_text("some content")
        result = read_file_for_quill(str(f))
        assert result is None

    def test_file_too_large(self, tmp_path):
        """A file > 500 KB returns None."""
        from axomind_mcp.tools._file_reader import read_file_for_quill

        f = tmp_path / "big.md"
        f.write_text("x" * (501 * 1024))
        result = read_file_for_quill(str(f))
        assert result is None

    def test_markdown_special_chars(self, tmp_path):
        """A .md file with special characters (---, |, quotes) does not crash."""
        from axomind_mcp.tools._file_reader import read_file_for_quill

        f = tmp_path / "special.md"
        f.write_text("# Title\n\n---\n\n| col1 | col2 |\n\n\"quoted\" and 'single'\n")
        result = read_file_for_quill(str(f))
        assert result is not None
        # Must be valid JSON
        ops = json.loads(result)
        assert isinstance(ops, list)

    def test_nonexistent_file(self):
        """A nonexistent file returns None."""
        from axomind_mcp.tools._file_reader import read_file_for_quill

        result = read_file_for_quill("/nonexistent/path/file.md")
        assert result is None

    def test_txt_with_special_chars(self, tmp_path):
        """A .txt file with quotes and backslashes produces valid JSON."""
        from axomind_mcp.tools._file_reader import read_file_for_quill

        f = tmp_path / "data.txt"
        f.write_text('Text with "quotes" and \\ backslash\n')
        result = read_file_for_quill(str(f))
        assert result is not None
        ops = json.loads(result)
        assert isinstance(ops, list)


class TestInjectDirectoryToMindmap:
    """Tests for inject_directory_to_mindmap — full directory injection."""

    def test_md_files_get_quill_descriptions(self, tmp_path):
        """Injecting a directory with .md files fills descriptions with Quill Delta."""
        from unittest.mock import patch

        from axomind_mcp.tools._tree import inject_directory_to_mindmap

        (tmp_path / "a.md").write_text("# Alpha\n\nContent A.\n")
        (tmp_path / "b.md").write_text("# Beta\n\nContent B.\n")

        with patch("axomind_mcp.tools._tree.sync_nodes") as mock_sync:
            mock_sync.return_value = '{"status":"ok"}'
            result_str = inject_directory_to_mindmap(str(tmp_path), "TestRoot", id_mindmap=42)
            result = json.loads(result_str)

        assert result["status"] == "success"
        assert result["total_nodes"] == 3  # root + 2 files
        assert result["descriptions_filled"] == 2
        assert result["files_ignored"] == 0
        # Verify sync_nodes was called
        mock_sync.assert_called_once()
        # Check that the synced nodes contain descriptions
        synced_json = mock_sync.call_args[0][1]
        synced_nodes = json.loads(synced_json)
        # Find file nodes (not root)
        file_nodes = [n for n in synced_nodes if n["title"] in ("a.md", "b.md")]
        assert len(file_nodes) == 2
        for fn in file_nodes:
            desc = fn.get("descriptions", "")
            assert desc  # non-empty
            ops = json.loads(desc)
            assert isinstance(ops, list)
            # Should contain header attributes
            assert any(op.get("attributes", {}).get("header") == 1 for op in ops)

    def test_txt_file_gets_plain_text_delta(self, tmp_path):
        """A .txt file gets a plain text Quill Delta description."""
        from unittest.mock import patch

        from axomind_mcp.tools._tree import inject_directory_to_mindmap

        (tmp_path / "notes.txt").write_text("Plain text content.\nNo markdown.")

        with patch("axomind_mcp.tools._tree.sync_nodes") as mock_sync:
            mock_sync.return_value = '{"status":"ok"}'
            result_str = inject_directory_to_mindmap(str(tmp_path), "Root", id_mindmap=42)
            result = json.loads(result_str)

        assert result["status"] == "success"
        assert result["descriptions_filled"] == 1
        synced_json = mock_sync.call_args[0][1]
        synced_nodes = json.loads(synced_json)
        txt_node = next(n for n in synced_nodes if n["title"] == "notes.txt")
        ops = json.loads(txt_node["descriptions"])
        assert len(ops) == 1
        assert "Plain text content" in ops[0]["insert"]

    def test_docx_file_empty_description(self, tmp_path):
        """A .docx file creates a node but with empty description."""
        from unittest.mock import patch

        from axomind_mcp.tools._tree import inject_directory_to_mindmap

        (tmp_path / "doc.docx").write_bytes(b"fake docx")

        with patch("axomind_mcp.tools._tree.sync_nodes") as mock_sync:
            mock_sync.return_value = '{"status":"ok"}'
            result_str = inject_directory_to_mindmap(str(tmp_path), "Root", id_mindmap=42)
            result = json.loads(result_str)

        assert result["status"] == "success"
        assert result["descriptions_filled"] == 0
        assert result["files_ignored"] == 1
        assert ".docx" in result["ignored_formats"]
        synced_json = mock_sync.call_args[0][1]
        synced_nodes = json.loads(synced_json)
        docx_node = next(n for n in synced_nodes if n["title"] == "doc.docx")
        assert docx_node["descriptions"] == ""

    def test_mixed_directory(self, tmp_path):
        """A directory with .md, .txt, and .docx files fills the right descriptions."""
        from unittest.mock import patch

        from axomind_mcp.tools._tree import inject_directory_to_mindmap

        (tmp_path / "readme.md").write_text("# Readme\n")
        (tmp_path / "data.txt").write_text("plain data\n")
        (tmp_path / "doc.docx").write_bytes(b"fake")

        with patch("axomind_mcp.tools._tree.sync_nodes") as mock_sync:
            mock_sync.return_value = '{"status":"ok"}'
            result_str = inject_directory_to_mindmap(str(tmp_path), "Root", id_mindmap=42)
            result = json.loads(result_str)

        assert result["status"] == "success"
        assert result["total_nodes"] == 4  # root + 3 files
        assert result["descriptions_filled"] == 2  # .md + .txt
        assert result["files_ignored"] == 1  # .docx

    def test_subdirectories_hierarchy(self, tmp_path):
        """Subdirectories produce correct hierarchy with descriptions only on leaves."""
        from unittest.mock import patch

        from axomind_mcp.tools._tree import inject_directory_to_mindmap

        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "nested.md").write_text("# Nested\n")
        (tmp_path / "top.md").write_text("# Top\n")

        with patch("axomind_mcp.tools._tree.sync_nodes") as mock_sync:
            mock_sync.return_value = '{"status":"ok"}'
            result_str = inject_directory_to_mindmap(str(tmp_path), "Root", id_mindmap=42)
            result = json.loads(result_str)

        assert result["status"] == "success"
        assert result["total_nodes"] == 4  # root + subdir + nested.md + top.md
        assert result["descriptions_filled"] == 2  # only files, not dirs
        synced_json = mock_sync.call_args[0][1]
        synced_nodes = json.loads(synced_json)
        # The directory node should NOT have descriptions
        dir_node = next(n for n in synced_nodes if n["title"] == "subdir")
        assert dir_node["descriptions"] == ""

    def test_empty_directory(self, tmp_path):
        """An empty directory produces just the root node, no crash."""
        from unittest.mock import patch

        from axomind_mcp.tools._tree import inject_directory_to_mindmap

        with patch("axomind_mcp.tools._tree.sync_nodes") as mock_sync:
            mock_sync.return_value = '{"status":"ok"}'
            result_str = inject_directory_to_mindmap(str(tmp_path), "Empty", id_mindmap=42)
            result = json.loads(result_str)

        assert result["status"] == "success"
        assert result["total_nodes"] == 1
        assert result["descriptions_filled"] == 0
        assert result["files_ignored"] == 0

    def test_markdown_with_special_chars(self, tmp_path):
        """Markdown with ---, |, quotes, and backticks doesn't crash."""
        from unittest.mock import patch

        from axomind_mcp.tools._tree import inject_directory_to_mindmap

        (tmp_path / "special.md").write_text(
            "# Title\n\n---\n\n| col1 | col2 |\n\n\"quoted\" 'single' `code`\n"
        )

        with patch("axomind_mcp.tools._tree.sync_nodes") as mock_sync:
            mock_sync.return_value = '{"status":"ok"}'
            result_str = inject_directory_to_mindmap(str(tmp_path), "Root", id_mindmap=42)
            result = json.loads(result_str)

        assert result["status"] == "success"
        assert result["descriptions_filled"] == 1
        synced_json = mock_sync.call_args[0][1]
        synced_nodes = json.loads(synced_json)
        md_node = next(n for n in synced_nodes if n["title"] == "special.md")
        # Description must be valid JSON
        ops = json.loads(md_node["descriptions"])
        assert isinstance(ops, list)

    def test_large_file_ignored(self, tmp_path):
        """A file > 500 KB gets a node but no description."""
        from unittest.mock import patch

        from axomind_mcp.tools._tree import inject_directory_to_mindmap

        (tmp_path / "big.md").write_text("x" * (501 * 1024))
        (tmp_path / "small.md").write_text("# Small\n")

        with patch("axomind_mcp.tools._tree.sync_nodes") as mock_sync:
            mock_sync.return_value = '{"status":"ok"}'
            result_str = inject_directory_to_mindmap(str(tmp_path), "Root", id_mindmap=42)
            result = json.loads(result_str)

        assert result["status"] == "success"
        assert result["descriptions_filled"] == 1  # only small.md
        assert result["files_ignored"] == 1  # big.md
        synced_json = mock_sync.call_args[0][1]
        synced_nodes = json.loads(synced_json)
        big_node = next(n for n in synced_nodes if n["title"] == "big.md")
        assert big_node["descriptions"] == ""

    def test_missing_mindmap_id(self, tmp_path):
        """Calling without id_mindmap returns an error."""
        from axomind_mcp.tools._tree import inject_directory_to_mindmap

        (tmp_path / "f.md").write_text("x")
        result_str = inject_directory_to_mindmap(str(tmp_path), "Root", id_mindmap=0)
        result = json.loads(result_str)
        assert "error" in result

    def test_nonexistent_path(self):
        """A nonexistent path returns an error."""
        from axomind_mcp.tools._tree import inject_directory_to_mindmap

        result_str = inject_directory_to_mindmap(
            "/nonexistent/path/xyz", "Root", id_mindmap=42
        )
        result = json.loads(result_str)
        assert "error" in result