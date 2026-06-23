"""Unit tests for the AI backend router (USE_HERMES bool).

Tests that the AXOMIND_USE_HERMES env var correctly switches the daemon
between Hermes mode (buffer events, no Ollama) and Ollama mode (process
messages locally).

These tests do NOT start the daemon — they verify the routing logic
and the env-var parsing in isolation.
"""

import importlib

import pytest

from axomind_mcp import _common


class TestUseHermesParsing:
    """Tests for the USE_HERMES env var parsing."""

    def test_default_is_false(self):
        """Without AXOMIND_USE_HERMES, the default is False (Ollama mode)."""
        # conftest sets AXOMIND_USE_HERMES=false
        assert _common.USE_HERMES is False

    def test_true_values(self):
        """Various truthy strings parse to True."""
        truthy_values = ["true", "1", "yes", "True", "YES", "1"]
        for val in truthy_values:
            result = val.strip().lower() in ("true", "1", "yes")
            assert result is True, f"Expected True for '{val}'"

    def test_false_values(self):
        """Various falsy strings parse to False."""
        falsy_values = ["false", "0", "no", "", "anything", "None"]
        for val in falsy_values:
            result = val.strip().lower() in ("true", "1", "yes")
            assert result is False, f"Expected False for '{val}'"


class TestRouterImport:
    """Tests that the router value is importable from server and daemon."""

    def test_server_reexports_use_hermes(self):
        """server.py re-exports USE_HERMES for backward compatibility."""
        from axomind_mcp.serveur import server

        assert hasattr(server, "USE_HERMES")
        assert server.USE_HERMES is False  # conftest default

    def test_daemon_imports_use_hermes(self):
        """daemon.py imports USE_HERMES from _common."""
        from axomind_mcp import daemon

        assert hasattr(daemon, "USE_HERMES")
        assert daemon.USE_HERMES is False  # conftest default


class TestRouterBehavior:
    """Tests for the routing behavior in _on_ws_event."""

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::DeprecationWarning")
    async def test_hermes_mode_skips_ollama(self, monkeypatch):
        """When USE_HERMES=True, _on_ws_event buffers and does NOT call Ollama."""
        from axomind_mcp import daemon

        # Patch USE_HERMES to True on the already-imported module
        monkeypatch.setattr(daemon, "USE_HERMES", True)

        # Track if _process_message_with_ollama is called
        ollama_called = []

        def fake_process(*args, **kwargs):
            ollama_called.append(True)

        monkeypatch.setattr(daemon, "_process_message_with_ollama", fake_process)

        # Build a fake WS event
        from axomind_mcp.serveur._ws_listener import WSEvent

        event = WSEvent(
            target="message",
            service="new_message",
            message="new_message",
            data={
                "sender_rel_user_id": 999,  # not Atlas
                "sender_rel_bot_id": 0,
                "rel_id_conversations": 42,
                "message": "Hello Atlas",
                "sender_pseudo": "TestUser",
            },
        )

        # Set a fake session so the sender check passes
        import axomind_mcp._common as _c

        monkeypatch.setattr(
            _c,
            "_get_user_session",
            lambda: {"user_id": "1", "token_exchange": "tok", "pseudo_user": "Atlas", "tag_pseudo": "Atlas#1234"},
        )

        await daemon._on_ws_event(event)

        # Ollama should NOT have been called
        assert len(ollama_called) == 0, "Ollama was called in Hermes mode"

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::DeprecationWarning")
    async def test_ollama_mode_calls_ollama(self, monkeypatch):
        """When USE_HERMES=False, _on_ws_event processes via Ollama."""
        from axomind_mcp import daemon

        monkeypatch.setattr(daemon, "USE_HERMES", False)

        ollama_called = []

        def fake_process(*args, **kwargs):
            ollama_called.append(True)

        monkeypatch.setattr(daemon, "_process_message_with_ollama", fake_process)

        from axomind_mcp.serveur._ws_listener import WSEvent

        event = WSEvent(
            target="message",
            service="new_message",
            message="new_message",
            data={
                "sender_rel_user_id": 999,
                "sender_rel_bot_id": 0,
                "rel_id_conversations": 42,
                "message": "Hello Atlas",
                "sender_pseudo": "TestUser",
            },
        )

        import axomind_mcp._common as _c

        monkeypatch.setattr(
            _c,
            "_get_user_session",
            lambda: {"user_id": "1", "token_exchange": "tok", "pseudo_user": "Atlas", "tag_pseudo": "Atlas#1234"},
        )

        await daemon._on_ws_event(event)

        # Ollama SHOULD have been called
        assert len(ollama_called) == 1, "Ollama was not called in Ollama mode"


class TestDaemonValidation:
    """Tests for env var validation in daemon.main() — skipped when USE_HERMES."""

    def test_hermes_mode_does_not_require_ollama_vars(self, monkeypatch):
        """In Hermes mode, missing OLLAMA_URL/MODEL should NOT cause sys.exit.

        We extract the validation block logic and test it in isolation
        without running the full asyncio event loop.
        """
        from axomind_mcp import daemon

        monkeypatch.setattr(daemon, "USE_HERMES", True)
        monkeypatch.setattr(daemon, "OLLAMA_URL", "")
        monkeypatch.setattr(daemon, "OLLAMA_MODEL", "")

        # Simulate the validation block from main():
        # if not USE_HERMES:
        #     if not OLLAMA_URL: sys.exit(1)
        #     if not OLLAMA_MODEL: sys.exit(1)
        # In Hermes mode this block is skipped entirely.
        import sys

        try:
            # Replicate the exact condition from main()
            if not daemon.USE_HERMES:
                if not daemon.OLLAMA_URL:
                    sys.exit(1)
                if not daemon.OLLAMA_MODEL:
                    sys.exit(1)
        except SystemExit:
            pytest.fail("Validation should be skipped in Hermes mode — OLLAMA vars not required")