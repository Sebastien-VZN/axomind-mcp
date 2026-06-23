"""Unit tests for the Axomind MCP server.

Mocks httpx to verify that tools build the correct requests
(URL, POST parameters, format) without touching the real server.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

# Env vars are set by tests/conftest.py with dummy values — no real credentials.
from axomind_mcp.serveur import server


class TestPostHelper:
    """Tests for the _post() helper"""

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_post_builds_correct_url(self, mock_post):
        """_post builds the URL with ?route=api_XXX"""
        mock_post.return_value = MagicMock(text='{"return_info": "ok"}')
        server._post("mindmap", "get_mindmaps")
        url = mock_post.call_args[0][0]
        assert url == "http://localhost/bot_api.php?route=api_mindmap"

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_post_includes_credentials(self, mock_post):
        """_post includes id_bot + key_access + type_action"""
        mock_post.return_value = MagicMock(text='{"return_info": "ok"}')
        server._post("activity", "get_activities")
        data = mock_post.call_args[1]["data"]
        assert data["id_bot"] == "999"
        assert data["key_access"] == "dummy_bot_key_for_tests"
        assert data["type_action"] == "get_activities"

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_post_passes_extra_params(self, mock_post):
        """_post passes kwargs as POST params"""
        mock_post.return_value = MagicMock(text='{"return_info": "ok"}')
        server._post("mindmap", "get_mindmap", id_mindmap=42)
        data = mock_post.call_args[1]["data"]
        assert data["id_mindmap"] == "42"

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_post_returns_response_text(self, mock_post):
        """_post returns the response body"""
        mock_post.return_value = MagicMock(text='{"return_info": "success"}')
        result = server._post("messenger", "add_message", content_message="hello")
        assert result == '{"return_info": "success"}'

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_post_handles_http_error(self, mock_post):
        """_post returns a JSON error if the request fails"""
        import httpx

        mock_post.side_effect = httpx.ConnectError("Connection refused")
        result = server._post("mindmap", "get_mindmaps")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "Connection refused" in parsed["error"]


class TestNodeExpansion:
    """Tests for the simplified node expansion helpers"""

    def test_expand_node_minimal(self):
        """_expand_node with only required fields"""
        node = server._expand_node(
            uid=1, order_index=1, parent_order_index=0, title="Root"
        )
        assert node["unique_const_id"] == "1"
        assert node["order_index"] == "1"
        assert node["parent_order_index"] == "0"
        assert node["title"] == "Root"
        assert node["color"] == server.DEFAULT_NODE_COLOR
        assert node["is_manual_position"] == "false"
        # Verify all default fields are present
        for key in server._NODE_DEFAULTS:
            assert key in node

    def test_expand_node_root_size_box(self):
        """_expand_node with size_box=2 sets is_manual_position=true"""
        node = server._expand_node(
            uid=1, order_index=1, parent_order_index=0, title="Root", size_box=2
        )
        assert node["index_size_box_node"] == 2
        assert node["is_manual_position"] == "true"

    def test_expand_node_custom_color(self):
        """_expand_node accepts a custom color"""
        node = server._expand_node(
            uid=2, order_index=2, parent_order_index=1, title="Child", color="0xFFFF6F91"
        )
        assert node["color"] == "0xFFFF6F91"

    def test_expand_node_style_options(self):
        """_expand_node accepts style overrides (bold, line_type, etc.)"""
        node = server._expand_node(
            uid=1, order_index=1, parent_order_index=0, title="Styled",
            bold=True, line_type=2, line_style=1, stroke_width=3.0,
        )
        assert node["bold_text"] is True
        assert node["type_node_connection"] == 2
        assert node["type_line_selector"] == 1
        assert node["stroke_width"] == 3.0

    def test_expand_node_free_links(self):
        """_expand_node accepts free_links and serializes them as JSON"""
        node = server._expand_node(
            uid=1, order_index=1, parent_order_index=0, title="Node",
            free_links=[3, 5],
        )
        assert node["free_link_order_index"] == "[3, 5]"

    def test_build_nodes_basic(self):
        """_build_nodes transforms a simple list into full nodes"""
        simple = [
            {"title": "Root", "parent": 0, "size_box": 2},
            {"title": "Child A", "parent": 1},
            {"title": "Child B", "parent": 1, "color": "0xFFFF6F91"},
        ]
        nodes = server._build_nodes(simple)
        assert len(nodes) == 3
        assert nodes[0]["title"] == "Root"
        assert nodes[0]["unique_const_id"] == "1"
        assert nodes[0]["order_index"] == "1"
        assert nodes[0]["parent_order_index"] == "0"
        assert nodes[0]["index_size_box_node"] == 2
        assert nodes[1]["title"] == "Child A"
        assert nodes[1]["parent_order_index"] == "1"
        assert nodes[2]["color"] == "0xFFFF6F91"

    def test_build_nodes_all_have_defaults(self):
        """All expanded nodes have the default fields"""
        simple = [{"title": "Test", "parent": 0}]
        nodes = server._build_nodes(simple)
        for key in server._NODE_DEFAULTS:
            assert key in nodes[0], f"Missing default key: {key}"

    def test_build_nodes_with_style(self):
        """_build_nodes passes style options through"""
        simple = [
            {"title": "Bold Node", "parent": 0, "bold": True, "label_size": 16},
            {"title": "Dashed Child", "parent": 1, "line_style": 1},
        ]
        nodes = server._build_nodes(simple)
        assert nodes[0]["bold_text"] is True
        assert nodes[0]["label_size"] == 16
        assert nodes[1]["type_line_selector"] == 1


class TestActivityTools:
    """Tests for Activity/Planning tools"""

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_list_activities(self, mock_post):
        mock_post.return_value = MagicMock(text='{"return_info": "ok", "activities": []}')
        result = server.list_activities()
        assert "activities" in result
        data = mock_post.call_args[1]["data"]
        assert data["type_action"] == "get_activities"

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_get_activity(self, mock_post):
        mock_post.return_value = MagicMock(text='{"return_info": "ok"}')
        server.get_activity(id_activity=2162)
        data = mock_post.call_args[1]["data"]
        assert data["id_activity"] == "2162"
        assert data["type_action"] == "get_activity"

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_add_assignment(self, mock_post):
        mock_post.return_value = MagicMock(text='{"return_info": "ok"}')
        planning = json.dumps([{"day": 1, "slots": []}])
        group = json.dumps({"title": "test", "active_days": "1111111"})
        server.add_assignment(
            id_activity=2162,
            planning_list=planning,
            recursive_group=group,
        )
        data = mock_post.call_args[1]["data"]
        assert data["id_activity"] == "2162"
        assert data["planning_list"] == planning
        assert data["recursive_group"] == group
        assert data["type_action"] == "add_assignment"

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_update_assignment(self, mock_post):
        mock_post.return_value = MagicMock(text='{"return_info": "ok"}')
        planning = json.dumps([{"day": 1}])
        group = json.dumps({"title": "updated"})
        server.update_assignment(
            id_activity=2162,
            update_assignement_id=99,
            planning_list=planning,
            recursive_group=group,
        )
        data = mock_post.call_args[1]["data"]
        assert data["update_assignement_id"] == "99"
        assert data["type_action"] == "update_assignment"

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_delete_assignment(self, mock_post):
        mock_post.return_value = MagicMock(text='{"return_info": "ok"}')
        server.delete_assignment(id_activity=2162, delete_recursive_group_slot=99)
        data = mock_post.call_args[1]["data"]
        assert data["delete_recursive_group_slot"] == "99"
        assert data["type_action"] == "delete_assignment"


class TestMindmapTools:
    """Tests for Mindmap tools"""

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_list_mindmaps(self, mock_post):
        mock_post.return_value = MagicMock(text='{"return_info": "ok", "mindmaps": []}')
        result = server.list_mindmaps()
        assert "mindmaps" in result
        data = mock_post.call_args[1]["data"]
        assert data["type_action"] == "get_mindmaps"

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_get_mindmap(self, mock_post):
        mock_post.return_value = MagicMock(text='{"return_info": "ok", "meta": {}, "nodes": []}')
        server.get_mindmap(id_mindmap=5)
        data = mock_post.call_args[1]["data"]
        assert data["id_mindmap"] == "5"
        assert data["type_action"] == "get_mindmap"

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_sync_nodes(self, mock_post):
        mock_post.return_value = MagicMock(text='{"return_info": "ok"}')
        nodes_json = json.dumps([{"order_index": 1, "title": "test"}])
        server.sync_nodes(id_mindmap=5, nodes=nodes_json)
        data = mock_post.call_args[1]["data"]
        assert data["id_mindmap"] == "5"
        assert data["nodes"] == nodes_json
        assert data["type_action"] == "sync_nodes"


class TestAddNodes:
    """Tests for the add_nodes high-level tool"""

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_add_nodes_appends_to_existing(self, mock_post):
        """add_nodes reads the existing mindmap and appends nodes"""
        existing = json.dumps({
            "return_info": "ok",
            "meta": {"id": 4697},
            "nodes": [
                {"unique_const_id": "1", "order_index": "1", "parent_order_index": "0", "title": "Root"},
            ],
        })
        sync_response = '{"return_info": "nodes synced successfully"}'

        # First call = get_mindmap, second = sync_nodes
        mock_post.side_effect = [
            MagicMock(text=existing),
            MagicMock(text=sync_response),
        ]

        simple_nodes = json.dumps([
            {"title": "Child A", "parent": 1},
            {"title": "Child B", "parent": 1, "color": "0xFFFF6F91"},
        ])
        result = server.add_nodes(id_mindmap=4697, nodes=simple_nodes)
        assert "synced successfully" in result

        # Check the second call (sync_nodes)
        sync_data = mock_post.call_args_list[1][1]["data"]
        all_nodes = json.loads(sync_data["nodes"])
        # 1 existing + 2 new = 3
        assert len(all_nodes) == 3
        # New nodes must have uid=2, oi=2
        assert all_nodes[1]["unique_const_id"] == "2"
        assert all_nodes[1]["order_index"] == "2"
        assert all_nodes[1]["parent_order_index"] == "1"
        assert all_nodes[1]["title"] == "Child A"
        assert all_nodes[2]["title"] == "Child B"
        assert all_nodes[2]["color"] == "0xFFFF6F91"

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_add_nodes_with_style(self, mock_post):
        """add_nodes passes style options through to expanded nodes"""
        existing = json.dumps({
            "return_info": "ok",
            "meta": {"id": 4697},
            "nodes": [
                {"unique_const_id": "1", "order_index": "1", "parent_order_index": "0", "title": "Root"},
            ],
        })
        sync_response = '{"return_info": "ok"}'

        mock_post.side_effect = [
            MagicMock(text=existing),
            MagicMock(text=sync_response),
        ]

        simple_nodes = json.dumps([
            {"title": "Bold Child", "parent": 1, "bold": True, "line_style": 1},
        ])
        server.add_nodes(id_mindmap=4697, nodes=simple_nodes)

        sync_data = mock_post.call_args_list[1][1]["data"]
        all_nodes = json.loads(sync_data["nodes"])
        assert all_nodes[1]["bold_text"] is True
        assert all_nodes[1]["type_line_selector"] == 1

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_add_nodes_invalid_json(self, mock_post):
        """add_nodes returns an error for invalid JSON"""
        result = server.add_nodes(id_mindmap=5, nodes="not json")
        parsed = json.loads(result)
        assert "error" in parsed

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_add_nodes_empty_array(self, mock_post):
        """add_nodes returns an error for an empty array"""
        result = server.add_nodes(id_mindmap=5, nodes="[]")
        parsed = json.loads(result)
        assert "error" in parsed


class TestReplaceMindmap:
    """Tests for the replace_mindmap high-level tool"""

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_replace_mindmap_expands_nodes(self, mock_post):
        """replace_mindmap expands simplified nodes and syncs"""
        mock_post.return_value = MagicMock(text='{"return_info": "nodes synced successfully"}')

        simple_nodes = json.dumps([
            {"title": "Root", "parent": 0, "size_box": 2, "color": "0xFFF0BA6D"},
            {"title": "Category A", "parent": 1, "color": "0xFF7A8FF5", "size_box": 1},
            {"title": "Item 1", "parent": 2},
        ])
        result = server.replace_mindmap(id_mindmap=4697, nodes=simple_nodes)
        assert "synced successfully" in result

        # Verify expanded nodes
        data = mock_post.call_args[1]["data"]
        all_nodes = json.loads(data["nodes"])
        assert len(all_nodes) == 3
        assert all_nodes[0]["title"] == "Root"
        assert all_nodes[0]["index_size_box_node"] == 2
        assert all_nodes[0]["color"] == "0xFFF0BA6D"
        assert all_nodes[1]["title"] == "Category A"
        assert all_nodes[1]["parent_order_index"] == "1"
        assert all_nodes[2]["title"] == "Item 1"
        assert all_nodes[2]["parent_order_index"] == "2"

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_replace_mindmap_with_style(self, mock_post):
        """replace_mindmap passes style options through"""
        mock_post.return_value = MagicMock(text='{"return_info": "ok"}')
        simple = json.dumps([
            {"title": "Root", "parent": 0, "bold": True, "label_size": 16},
            {"title": "Child", "parent": 1, "line_type": 2, "free_links": [1]},
        ])
        server.replace_mindmap(id_mindmap=5, nodes=simple)
        data = mock_post.call_args[1]["data"]
        nodes = json.loads(data["nodes"])
        assert nodes[0]["bold_text"] is True
        assert nodes[0]["label_size"] == 16
        assert nodes[1]["type_node_connection"] == 2
        assert nodes[1]["free_link_order_index"] == "[1]"

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_replace_mindmap_invalid_json(self, mock_post):
        """replace_mindmap returns an error for invalid JSON"""
        result = server.replace_mindmap(id_mindmap=5, nodes="invalid")
        parsed = json.loads(result)
        assert "error" in parsed

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_replace_mindmap_empty_array(self, mock_post):
        """replace_mindmap returns an error for an empty array"""
        result = server.replace_mindmap(id_mindmap=5, nodes="[]")
        parsed = json.loads(result)
        assert "error" in parsed

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_replace_mindmap_has_all_defaults(self, mock_post):
        """replace_mindmap fills all default fields"""
        mock_post.return_value = MagicMock(text='{"return_info": "ok"}')
        simple = json.dumps([{"title": "Test", "parent": 0}])
        server.replace_mindmap(id_mindmap=5, nodes=simple)
        data = mock_post.call_args[1]["data"]
        nodes = json.loads(data["nodes"])
        for key in server._NODE_DEFAULTS:
            assert key in nodes[0], f"Missing default key: {key}"


class TestNodeValidation:
    """Tests for hierarchy validation — prevents Flutter client crashes"""

    def test_validate_self_reference_parent_rejected(self):
        """A node whose parent equals its own order_index must be rejected"""
        from axomind_mcp.mindmap.config_layout_mindmap import _validate_simplified_nodes
        bad = [
            {"title": "Root", "parent": 0},
            {"title": "Self", "parent": 2},
        ]
        error = _validate_simplified_nodes(bad)
        assert error is not None
        assert "self-reference" in error

    def test_validate_forward_reference_rejected(self):
        """A node whose parent points to a later node must be rejected"""
        from axomind_mcp.mindmap.config_layout_mindmap import _validate_simplified_nodes
        bad = [
            {"title": "Root", "parent": 0},
            {"title": "A", "parent": 3},
            {"title": "B", "parent": 1},
        ]
        error = _validate_simplified_nodes(bad)
        assert error is not None
        assert "forward-reference" in error

    def test_validate_valid_hierarchy_passes(self):
        """A correct parent→child chain must pass validation"""
        from axomind_mcp.mindmap.config_layout_mindmap import _validate_simplified_nodes
        good = [
            {"title": "Root", "parent": 0},
            {"title": "Client", "parent": 1},
            {"title": "Server", "parent": 2},
            {"title": "WS", "parent": 3, "free_links": [2]},
        ]
        error = _validate_simplified_nodes(good)
        assert error is None

    def test_validate_free_link_self_rejected(self):
        """A free_link targeting the node itself must be rejected"""
        from axomind_mcp.mindmap.config_layout_mindmap import _validate_simplified_nodes
        bad = [
            {"title": "Root", "parent": 0},
            {"title": "A", "parent": 1, "free_links": [2]},
        ]
        error = _validate_simplified_nodes(bad)
        assert error is not None
        assert "free_link targets self" in error

    def test_validate_free_link_out_of_range_rejected(self):
        """A free_link targeting a non-existent node must be rejected"""
        from axomind_mcp.mindmap.config_layout_mindmap import _validate_simplified_nodes
        bad = [
            {"title": "Root", "parent": 0},
            {"title": "A", "parent": 1, "free_links": [99]},
        ]
        error = _validate_simplified_nodes(bad)
        assert error is not None
        assert "out of range" in error

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_replace_mindmap_rejects_self_reference(self, mock_post):
        """replace_mindmap must reject nodes with self-referencing parent"""
        bad = json.dumps([
            {"title": "Root", "parent": 0},
            {"title": "Client", "parent": 2},
            {"title": "Server", "parent": 3},
        ])
        result = server.replace_mindmap(id_mindmap=5, nodes=bad)
        parsed = json.loads(result)
        assert "error" in parsed
        assert "self-reference" in parsed["error"]
        mock_post.assert_not_called()

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_replace_mindmap_accepts_valid_hierarchy(self, mock_post):
        """replace_mindmap must accept a valid parent→child chain"""
        mock_post.return_value = MagicMock(text='{"return_info": "ok"}')
        good = json.dumps([
            {"title": "Root", "parent": 0, "size_box": 2},
            {"title": "Client", "parent": 1, "size_box": 1},
            {"title": "Server", "parent": 2, "size_box": 1},
            {"title": "WS", "parent": 3, "free_links": [2]},
        ])
        result = server.replace_mindmap(id_mindmap=5, nodes=good)
        assert "ok" in result


class TestTopologyPositions:
    """Tests for auto-positioning of topology nodes (hierarchical tree layout, retrospective mode)"""

    def test_calculate_positions_4_node_chain(self):
        """Linear chain Root→A→B→C: depth-based X, leaves spread on Y, parents centered"""
        from axomind_mcp.mindmap.config_layout_mindmap import _calculate_topology_positions, GRID_CELL, ROOT_X, DEPTH_STEP_X, ROOT_Y
        nodes = [
            {"title": "Root", "parent": 0},
            {"title": "Client", "parent": 1},
            {"title": "Server", "parent": 2},
            {"title": "WS", "parent": 3, "free_links": [2]},
        ]
        result = _calculate_topology_positions(nodes)
        # All nodes manual
        for n in result:
            assert n["is_manual_position"] is True
        # Depth 0 (root): X = ROOT_X
        assert result[0]["pos_x"] == str(ROOT_X)  # 240
        # Depth 1: X = ROOT_X + 1*DEPTH_STEP_X = 240+240 = 480
        assert result[1]["pos_x"] == str(ROOT_X + DEPTH_STEP_X)  # 480
        # Depth 2: X = ROOT_X + 2*DEPTH_STEP_X = 240+480 = 720
        assert result[2]["pos_x"] == str(ROOT_X + 2 * DEPTH_STEP_X)  # 720
        # Depth 3: X = ROOT_X + 3*DEPTH_STEP_X = 240+720 = 960
        assert result[3]["pos_x"] == str(ROOT_X + 3 * DEPTH_STEP_X)  # 960
        # Linear chain: all leaves, so all at ROOT_Y + i*120 (all same Y since each is the only leaf)
        # Actually in a linear chain, each node IS a leaf (single child parent), so Y = ROOT_Y for all
        assert result[0]["pos_y"] == str(ROOT_Y)
        assert result[3]["pos_y"] == str(ROOT_Y)

    def test_calculate_positions_2_nodes(self):
        """With only 2 nodes, root and child are both manual"""
        from axomind_mcp.mindmap.config_layout_mindmap import _calculate_topology_positions, ROOT_X, DEPTH_STEP_X
        nodes = [
            {"title": "Root", "parent": 0},
            {"title": "Child", "parent": 1},
        ]
        result = _calculate_topology_positions(nodes)
        assert result[0]["is_manual_position"] is True
        assert result[0]["pos_x"] == str(ROOT_X)
        assert result[1]["pos_x"] == str(ROOT_X + DEPTH_STEP_X)
        assert result[1]["is_manual_position"] is True

    def test_all_positions_are_multiples_of_60(self):
        """Every calculated position must be a strict multiple of GRID_CELL (60)"""
        from axomind_mcp.mindmap.config_layout_mindmap import _calculate_topology_positions, GRID_CELL
        # Complex tree: 10 nodes with branches
        nodes = [
            {"title": "Root", "parent": 0},
            {"title": "A", "parent": 1},
            {"title": "B", "parent": 2},
            {"title": "C", "parent": 2},
            {"title": "D", "parent": 1},
            {"title": "E", "parent": 5},
            {"title": "F", "parent": 5},
            {"title": "G", "parent": 5},
            {"title": "H", "parent": 8, "free_links": [2]},
            {"title": "I", "parent": 9},
        ]
        result = _calculate_topology_positions(nodes)
        for node in result:
            px = int(node["pos_x"])
            py = int(node["pos_y"])
            assert px % GRID_CELL == 0, f"pos_x={px} is not a multiple of {GRID_CELL}"
            assert py % GRID_CELL == 0, f"pos_y={py} is not a multiple of {GRID_CELL}"

    def test_ai_provided_positions_are_respected(self):
        """When the AI provides pos_x/pos_y, they must NOT be overwritten"""
        from axomind_mcp.mindmap.config_layout_mindmap import _calculate_topology_positions
        nodes = [
            {"title": "Root", "parent": 0, "pos_x": "600", "pos_y": "300"},
            {"title": "Client", "parent": 1, "pos_x": "1200", "pos_y": "600"},
            {"title": "Server", "parent": 2, "pos_x": "1800", "pos_y": "300"},
            {"title": "WS", "parent": 3, "free_links": [2]},
        ]
        result = _calculate_topology_positions(nodes)
        # AI-provided positions preserved
        assert result[0]["pos_x"] == "600"
        assert result[0]["pos_y"] == "300"
        assert result[0]["is_manual_position"] is True
        assert result[1]["pos_x"] == "1200"
        assert result[1]["pos_y"] == "600"
        assert result[1]["is_manual_position"] is True
        assert result[2]["pos_x"] == "1800"
        assert result[2]["pos_y"] == "300"
        assert result[2]["is_manual_position"] is True
        # Node 4 (WS) has no AI positions → gets calculated
        assert result[3]["is_manual_position"] is True
        # Depth 3: ROOT_X + 3*DEPTH_STEP_X = 240+720 = 960
        assert result[3]["pos_x"] == "960"

    def test_is_manual_position_true_for_all_positioned_nodes(self):
        """All nodes that receive positions (AI or calculated) must have is_manual_position=True"""
        from axomind_mcp.mindmap.config_layout_mindmap import _calculate_topology_positions
        nodes = [
            {"title": "Root", "parent": 0},
            {"title": "A", "parent": 1},
            {"title": "B", "parent": 2, "pos_x": "720", "pos_y": "420"},
            {"title": "C", "parent": 3, "free_links": [2]},
            {"title": "D", "parent": 4},
        ]
        result = _calculate_topology_positions(nodes)
        for node in result:
            assert node["is_manual_position"] is True, f"Node '{node['title']}' should have is_manual_position=True"

    def test_parents_centered_on_children(self):
        """Parent Y should be the median of its children's Y positions"""
        from axomind_mcp.mindmap.config_layout_mindmap import _calculate_topology_positions, ROOT_Y, SIBLING_STEP_Y
        nodes = [
            {"title": "Root", "parent": 0},
            {"title": "A", "parent": 1},
            {"title": "B", "parent": 2},
            {"title": "C", "parent": 2},
            {"title": "D", "parent": 2, "free_links": [1]},
        ]
        result = _calculate_topology_positions(nodes)
        # Children of node 2 (A): B, C, D are leaves at depth 2
        # Leaves in DFS order: Root? No — Root has child A, A has children B,C,D
        # Leaves: B, C, D → Y = ROOT_Y, ROOT_Y+120, ROOT_Y+240
        y_b = int(result[2]["pos_y"])
        y_c = int(result[3]["pos_y"])
        y_d = int(result[4]["pos_y"])
        # A (parent of B,C,D) should be at median = Y of C (middle child)
        y_a = int(result[1]["pos_y"])
        assert y_a == y_c  # A centered on its children

    def test_depth_increases_x(self):
        """Deeper nodes must have larger X (tree grows right)"""
        from axomind_mcp.mindmap.config_layout_mindmap import _calculate_topology_positions
        nodes = [
            {"title": "Root", "parent": 0},
            {"title": "L1", "parent": 1},
            {"title": "L2", "parent": 2},
            {"title": "L3", "parent": 3, "free_links": [1]},
        ]
        result = _calculate_topology_positions(nodes)
        x0 = int(result[0]["pos_x"])
        x1 = int(result[1]["pos_x"])
        x2 = int(result[2]["pos_x"])
        x3 = int(result[3]["pos_x"])
        assert x0 < x1 < x2 < x3  # strictly increasing

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_replace_mindmap_auto_positions_topology(self, mock_post):
        """replace_mindmap auto-positions nodes when free_links are present"""
        mock_post.return_value = MagicMock(text='{"return_info": "ok"}')
        simple = json.dumps([
            {"title": "Root", "parent": 0, "size_box": 2},
            {"title": "Client", "parent": 1},
            {"title": "Server", "parent": 2},
            {"title": "WS", "parent": 3, "free_links": [2]},
        ])
        server.replace_mindmap(id_mindmap=5, nodes=simple)
        data = mock_post.call_args[1]["data"]
        nodes = json.loads(data["nodes"])
        # All nodes should have manual positions
        for n in nodes:
            assert n["is_manual_position"] == "true"
            assert n["pos_x"] != "0"
        # X increases with depth
        assert int(nodes[0]["pos_x"]) < int(nodes[1]["pos_x"])
        assert int(nodes[1]["pos_x"]) < int(nodes[2]["pos_x"])
        assert int(nodes[2]["pos_x"]) < int(nodes[3]["pos_x"])

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_replace_mindmap_no_auto_position_without_free_links(self, mock_post):
        """replace_mindmap does NOT auto-position when there are no free_links"""
        mock_post.return_value = MagicMock(text='{"return_info": "ok"}')
        simple = json.dumps([
            {"title": "Root", "parent": 0, "size_box": 2},
            {"title": "Child A", "parent": 1},
            {"title": "Child B", "parent": 1},
        ])
        server.replace_mindmap(id_mindmap=5, nodes=simple)
        data = mock_post.call_args[1]["data"]
        nodes = json.loads(data["nodes"])
        # Without free_links, no auto-positioning — pos stays at default "0"
        assert nodes[1]["pos_x"] == "0"
        assert nodes[2]["pos_x"] == "0"

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_replace_mindmap_respects_ai_positions(self, mock_post):
        """replace_mindmap preserves AI-provided pos_x/pos_y, does not overwrite"""
        mock_post.return_value = MagicMock(text='{"return_info": "ok"}')
        simple = json.dumps([
            {"title": "Root", "parent": 0, "size_box": 2, "pos_x": "600", "pos_y": "300"},
            {"title": "Client", "parent": 1, "pos_x": "1200", "pos_y": "600"},
            {"title": "Server", "parent": 2, "pos_x": "1800", "pos_y": "300"},
            {"title": "WS", "parent": 3, "free_links": [2]},
        ])
        server.replace_mindmap(id_mindmap=5, nodes=simple)
        data = mock_post.call_args[1]["data"]
        nodes = json.loads(data["nodes"])
        # AI-provided positions must be preserved
        assert nodes[0]["pos_x"] == "600"
        assert nodes[0]["pos_y"] == "300"
        assert nodes[0]["is_manual_position"] == "true"
        assert nodes[1]["pos_x"] == "1200"
        assert nodes[1]["pos_y"] == "600"
        assert nodes[2]["pos_x"] == "1800"
        assert nodes[2]["pos_y"] == "300"


class TestMessengerTools:
    """Tests for Messenger tools"""

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_send_message_broadcast(self, mock_post):
        """send_message without id_conversation = broadcast (0)"""
        mock_post.return_value = MagicMock(text='{"return_info": "ok"}')
        server.send_message(content_message="hello")
        data = mock_post.call_args[1]["data"]
        assert data["content_message"] == "hello"
        assert data["id_conversation"] == "0"
        assert data["type_action"] == "add_message"

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_send_message_targeted(self, mock_post):
        """send_message with id_conversation = targeted"""
        mock_post.return_value = MagicMock(text='{"return_info": "ok"}')
        server.send_message(content_message="hello", id_conversation=42)
        data = mock_post.call_args[1]["data"]
        assert data["id_conversation"] == "42"

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_get_messages(self, mock_post):
        mock_post.return_value = MagicMock(text='{"return_info": "ok", "messages": []}')
        server.get_messages(id_conversation=42)
        data = mock_post.call_args[1]["data"]
        assert data["id_conversation"] == "42"
        assert data["type_action"] == "get_messages"

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_update_message(self, mock_post):
        mock_post.return_value = MagicMock(text='{"return_info": "ok"}')
        server.update_message(update_message_id=99, content_message="updated")
        data = mock_post.call_args[1]["data"]
        assert data["update_message_id"] == "99"
        assert data["content_message"] == "updated"
        assert data["type_action"] == "update_message"

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_delete_message(self, mock_post):
        mock_post.return_value = MagicMock(text='{"return_info": "ok"}')
        server.delete_message(delete_message_id=99)
        data = mock_post.call_args[1]["data"]
        assert data["delete_message_id"] == "99"
        assert data["type_action"] == "delete_message"


class TestUserHelper:
    """Tests for the _post_user() helper"""

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_post_user_builds_correct_url(self, mock_post):
        """_post_user builds URL with ?rt=<ROUTE_PREFIX><route>"""
        mock_post.return_value = MagicMock(text='{"return_code": 0}')
        server._post_user("auth_action", require_auth=False)
        url = mock_post.call_args[0][0]
        assert "index.php" in url
        assert "rt=test_rt_auth_action" in url

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_post_user_includes_keypass_and_type_client(self, mock_post):
        """_post_user always includes KEY_PASS and type_client"""
        mock_post.return_value = MagicMock(text='{"return_code": 0}')
        server._post_user("read_conversations", require_auth=False)
        data = mock_post.call_args[1]["data"]
        assert "KEY_PASS" in data
        assert "type_client" in data

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_post_user_no_auth_skips_session(self, mock_post):
        """_post_user with require_auth=False does not send user_id/token"""
        mock_post.return_value = MagicMock(text='{"return_code": 0}')
        server._post_user("auth_action", require_auth=False)
        data = mock_post.call_args[1]["data"]
        assert "user_id" not in data
        assert "token_exchange" not in data

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_post_user_with_auth_includes_session(self, mock_post):
        """_post_user with require_auth=True sends user_id + token from session"""
        mock_post.return_value = MagicMock(text='{"return_code": 0}')
        server._update_user_session("42", "tok123")
        server._post_user("read_conversations")
        data = mock_post.call_args[1]["data"]
        assert data["user_id"] == "42"
        assert data["token_exchange"] == "tok123"

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_post_user_passes_extra_params(self, mock_post):
        """_post_user passes kwargs as POST params"""
        mock_post.return_value = MagicMock(text='{"return_code": 0}')
        server._post_user("post_invitation", require_auth=False, valide_invite_user="1")
        data = mock_post.call_args[1]["data"]
        assert data["valide_invite_user"] == "1"

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_post_user_handles_http_error(self, mock_post):
        """_post_user returns JSON error on connection failure"""
        import httpx
        mock_post.side_effect = httpx.ConnectError("Connection refused")
        result = server._post_user("auth_action", require_auth=False)
        parsed = json.loads(result)
        assert "error" in parsed

    def test_update_and_get_user_session(self):
        """_update_user_session and _get_user_session work correctly"""
        server._update_user_session("99", "tok456", pseudo="Atlas", tag="atlas#abc")
        session = server._get_user_session()
        assert session["user_id"] == "99"
        assert session["token_exchange"] == "tok456"
        assert session["pseudo_user"] == "Atlas"
        assert session["tag_pseudo"] == "atlas#abc"


class TestUserLogin:
    """Tests for user_login tool"""

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_login_sends_correct_params(self, mock_post):
        """user_login sends email, pre_auth, password, type_client"""
        mock_post.return_value = MagicMock(
            text=json.dumps({
                "return_code": 0,
                "user_id": 42,
                "token_exchange": "tok123",
                "pseudo_user": "Atlas",
                "tag_pseudo": "atlas#abc",
            })
        )
        server.user_login()
        data = mock_post.call_args[1]["data"]
        assert data["pre_auth"] == "1"
        assert "email_user" in data
        assert "password" in data
        assert "type_client" in data

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_login_stores_session_on_success(self, mock_post):
        """user_login stores user_id and token in session on return_code=0"""
        mock_post.return_value = MagicMock(
            text=json.dumps({
                "return_code": 0,
                "user_id": 42,
                "token_exchange": "tok123",
                "pseudo_user": "Atlas",
                "tag_pseudo": "atlas#abc",
            })
        )
        server.user_login()
        session = server._get_user_session()
        assert session["user_id"] == "42"
        assert session["token_exchange"] == "tok123"
        assert session["pseudo_user"] == "Atlas"
        assert session["tag_pseudo"] == "atlas#abc"

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_login_does_not_store_session_on_failure(self, mock_post):
        """user_login does not store session on return_code != 0"""
        mock_post.return_value = MagicMock(
            text=json.dumps({"return_code": 1})
        )
        server._update_user_session("", "")
        server.user_login()
        session = server._get_user_session()
        assert session["user_id"] == ""
        assert session["token_exchange"] == ""


class TestUserRenewToken:
    """Tests for user_renew_token tool"""

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_renew_sends_correct_params(self, mock_post):
        """user_renew_token sends renew_auth=1 with current session"""
        mock_post.return_value = MagicMock(
            text=json.dumps({"return_code": 0, "token_exchange": "newtok"})
        )
        server._update_user_session("42", "oldtok")
        server.user_renew_token()
        data = mock_post.call_args[1]["data"]
        assert data["renew_auth"] == "1"
        assert data["user_id"] == "42"
        assert data["token_exchange"] == "oldtok"

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_renew_updates_token_on_success(self, mock_post):
        """user_renew_token updates the session token on return_code=0"""
        mock_post.return_value = MagicMock(
            text=json.dumps({"return_code": 0, "token_exchange": "newtok"})
        )
        server._update_user_session("42", "oldtok")
        server.user_renew_token()
        session = server._get_user_session()
        assert session["token_exchange"] == "newtok"


class TestUserStatus:
    """Tests for user_status tool"""

    def test_status_not_logged_in(self):
        """user_status shows logged_in=false when no session"""
        server._update_user_session("", "")
        result = json.loads(server.user_status())
        assert result["logged_in"] is False
        assert result["user_id"] == ""

    def test_status_logged_in(self):
        """user_status shows logged_in=true when session is active"""
        server._update_user_session("42", "tok123", pseudo="Atlas", tag="atlas#abc")
        result = json.loads(server.user_status())
        assert result["logged_in"] is True
        assert result["user_id"] == "42"
        assert result["pseudo_user"] == "Atlas"
        assert result["tag_pseudo"] == "atlas#abc"


class TestUserInvitations:
    """Tests for invitation tools"""

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_get_pending_invitations(self, mock_post):
        """user_get_pending_invitations sends get_pending_users with user_id"""
        mock_post.return_value = MagicMock(text="[]")
        server._update_user_session("42", "tok123")
        server.user_get_pending_invitations()
        data = mock_post.call_args[1]["data"]
        assert data["get_pending_users"] == "42"
        assert "KEY_PASS" in data

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_accept_invitation_sends_correct_params(self, mock_post):
        """user_accept_invitation sends valide_invite_user with sender + target.

        After the sender/target fix (2026-06-22):
          - sender_user_id = session user_id (Atlas, the one validating)
          - target_user_id = the invitation sender's user_id
        """
        mock_post.return_value = MagicMock(
            text=json.dumps({"return_code": 0, "id_last_conv": 99})
        )
        server._update_user_session("42", "tok123")
        server.user_accept_invitation(sender_user_id=10)
        data = mock_post.call_args[1]["data"]
        assert data["valide_invite_user"] == "1"
        assert data["sender_user_id"] == "42"
        assert data["target_user_id"] == "10"
        assert data["select_lang"] == "fr_FR"

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_refuse_invitation_sends_correct_params(self, mock_post):
        """user_refuse_invitation sends refus_invite_user with sender + target.

        After the sender/target fix (2026-06-22):
          - sender_user_id = session user_id (Atlas, the one refusing)
          - target_user_id = the invitation sender's user_id
        """
        mock_post.return_value = MagicMock(text='{"return_code": 0}')
        server._update_user_session("42", "tok123")
        server.user_refuse_invitation(sender_user_id=10)
        data = mock_post.call_args[1]["data"]
        assert data["refus_invite_user"] == "1"
        assert data["sender_user_id"] == "42"
        assert data["target_user_id"] == "10"


class TestUserMessaging:
    """Tests for user messaging tools"""

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_get_conversations(self, mock_post):
        """user_get_conversations sends get_list=1"""
        mock_post.return_value = MagicMock(text="[]")
        server._update_user_session("42", "tok123")
        server.user_get_conversations()
        data = mock_post.call_args[1]["data"]
        assert data["get_list"] == "1"

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_send_message(self, mock_post):
        """user_send_message sends add_message with content and conversation id.

        The PHP route post_conversation expects 'message' (not 'content_message')
        as the parameter name, plus sender_rel_user_id and rel_id_conversations.
        """
        mock_post.return_value = MagicMock(
            text=json.dumps({"return_code": 0, "id": 55})
        )
        server._update_user_session("42", "tok123")
        server.user_send_message(content_message="hello world", id_conversation=99)
        data = mock_post.call_args[1]["data"]
        assert data["add_message"] == "1"
        assert data["message"] == "hello world"
        assert data["rel_id_conversations"] == "99"
        assert data["sender_rel_user_id"] == "42"

    @patch("axomind_mcp.serveur.server.httpx.post")
    def test_send_message_targets_user_api_not_bot_api(self, mock_post):
        """user_send_message targets index.php (user API), not bot_api.php"""
        mock_post.return_value = MagicMock(
            text=json.dumps({"return_code": 0, "id": 55})
        )
        server._update_user_session("42", "tok123")
        server.user_send_message(content_message="test", id_conversation=99)
        url = mock_post.call_args[0][0]
        assert "index.php" in url
        assert "bot_api.php" not in url


class TestUserToolRegistration:
    """Verify user tools are registered with the MCP server"""

    def test_user_tools_registered(self):
        """All 9 user tools must be registered"""
        expected = {
            "user_login",
            "user_renew_token",
            "user_status",
            "user_get_pending_invitations",
            "user_accept_invitation",
            "user_refuse_invitation",
            "user_get_conversations",
            "user_send_message",
            "user_poll_events",
        }
        registered = set(server.mcp._tool_manager._tools.keys())
        missing = expected - registered
        assert not missing, f"Missing user tools: {missing}"


class TestAllToolRegistration:
    """Verify ALL tools (bot + user) are registered with the MCP server"""

    def test_all_tools_registered(self):
        """All 24 tools (15 bot + 9 user) must be registered"""
        expected = {
            # Bot tools (15)
            "list_activities",
            "get_activity",
            "add_assignment",
            "update_assignment",
            "delete_assignment",
            "list_mindmaps",
            "get_mindmap",
            "sync_nodes",
            "add_nodes",
            "replace_mindmap",
            "update_nodes_style",
            "send_message",
            "get_messages",
            "update_message",
            "delete_message",
            # User tools (9)
            "user_login",
            "user_renew_token",
            "user_status",
            "user_get_pending_invitations",
            "user_accept_invitation",
            "user_refuse_invitation",
            "user_get_conversations",
            "user_send_message",
            "user_poll_events",
        }
        registered = set(server.mcp._tool_manager._tools.keys())
        missing = expected - registered
        assert not missing, f"Missing tools: {missing}"
        # Also verify total count
        assert len(registered) >= 24, f"Expected >= 24 tools, got {len(registered)}"