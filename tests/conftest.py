"""Shared pytest fixtures and env-var setups for Axomind MCP tests.

Sets DUMMY environment variables before the server module is imported.
No real credentials are stored here — tests mock httpx and never hit a live server.
"""

import os

# Dummy values — no real credentials. Tests mock httpx.post, these only
# satisfy the module-level os.environ.get() calls in _common.py at import time.
os.environ.setdefault("AXOMIND_BOT_ID", "999")
os.environ.setdefault("AXOMIND_BOT_KEY", "dummy_bot_key_for_tests")
os.environ.setdefault("AXOMIND_BASE_URL", "http://localhost/bot_api.php")
os.environ.setdefault("AXOMIND_USER_BASE_URL", "http://localhost/index.php")
os.environ.setdefault("AXOMIND_ROUTE_PREFIX", "test_rt_")
os.environ.setdefault("AXOMIND_KEY_PASS", "dummy_keypass_for_tests")
os.environ.setdefault("AXOMIND_USER_EMAIL", "test_bot@example.com")
os.environ.setdefault("AXOMIND_USER_PASSWORD", "dummy_password_for_tests")
os.environ.setdefault("AXOMIND_USER_TYPE_CLIENT", "test_client")
# AI backend router — default to Ollama mode for existing tests
os.environ.setdefault("AXOMIND_USE_HERMES", "false")
# WS listener + daemon (dummy values — tests mock httpx, never connect for real)
os.environ.setdefault("AXOMIND_WS_URL", "ws://localhost:8080/")
os.environ.setdefault("AXOMIND_OLLAMA_URL", "http://localhost:11434/v1/chat/completions")
os.environ.setdefault("AXOMIND_OLLAMA_MODEL", "dummy_model_for_tests")