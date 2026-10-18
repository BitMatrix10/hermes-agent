"""Compact gateway tool progress: ``tool_progress_terminal_blocks`` and ``tool_progress_compact``."""

import pytest

from gateway.display_config import resolve_display_setting
from gateway.run_turn_progress import GatewayTurnProgressMixin as Mixin
from tests.gateway.test_run_progress_topics import ProgressCaptureAdapter, _run_with_agent
from tests.waiting import wait_until

COMMANDS = ("ls -la", "cat /etc/hostname", "echo hi")
LONG = "/home/u/projects/some/very/deep/directory/structure/important_file.py"


class _CodeBlockAdapter(ProgressCaptureAdapter):
    supports_code_blocks = True


class _ToolsAgent:
    """Three different terminal commands, then one file read with a long path."""

    adapter = None

    def __init__(self, **kwargs):
        self.tool_progress_callback = kwargs.get("tool_progress_callback")
        self.tools = []

    def run_conversation(self, message, conversation_history=None, task_id=None, **kwargs):
        for cmd in COMMANDS:
            self.tool_progress_callback("tool.started", "terminal", cmd, {"command": cmd})
        self.tool_progress_callback("tool.started", "read_file", LONG, {"path": LONG})
        wait_until(lambda: _ToolsAgent.adapter.sent, what="the progress bubble was sent")
        return {"final_response": "done", "messages": [], "api_calls": 1}


async def _progress_text(monkeypatch, tmp_path, display: dict) -> str:
    class Capture(_CodeBlockAdapter):
        def __init__(self, **kw):
            super().__init__(**kw)
            _ToolsAgent.adapter = self

    adapter, _ = await _run_with_agent(monkeypatch, tmp_path, _ToolsAgent, session_id=f"sess-{sorted(display.items())}",
                                       config_data={"display": {"tool_progress": "all", **display}}, adapter_cls=Capture)
    # The last edit of the accumulated bubble holds every line.
    return (adapter.edits or adapter.sent)[-1]["content"]


@pytest.mark.asyncio
async def test_default_keeps_terminal_code_blocks(monkeypatch, tmp_path):
    text = await _progress_text(monkeypatch, tmp_path, {})
    assert "```" in text and "cat /etc/hostname" in text, text


@pytest.mark.asyncio
async def test_terminal_blocks_off_renders_one_line_labels(monkeypatch, tmp_path):
    text = await _progress_text(monkeypatch, tmp_path, {"tool_progress_terminal_blocks": False})
    assert "```" not in text, text


@pytest.mark.asyncio
async def test_compact_collapses_commands_and_shortens_paths(monkeypatch, tmp_path):
    text = await _progress_text(monkeypatch, tmp_path, {"tool_progress_compact": True})
    assert "terminal (×3)" in text, text
    assert not any(cmd in text for cmd in COMMANDS), text
    assert "read_file: …/structure/important_file.py" in text, text


@pytest.mark.parametrize("path,cap,want", [
    ("/home/u/.hermes/data/media_watchdog/events.log", 30, "…/media_watchdog/events.log"),
    ("~/short.md", 30, "~/short.md"),
    ("/a/b/a_really_long_filename_that_is_longer_than_thirty.py", 30,
     "a_really_long_filename_that_is_longer_than_thirty.py"),
    ("C:\\Users\\u\\file.txt", 0, "C:/Users/u/file.txt"),
])
def test_shorten_path_trims_from_the_front_and_keeps_the_file_name(path, cap, want):
    assert Mixin._shorten_path(path, cap) == want


def test_settings_resolve_per_platform():
    cfg = {"display": {"tool_progress_compact": "yes", "tool_progress_terminal_blocks": False,
                       "platforms": {"slack": {"tool_progress_terminal_blocks": True}}}}
    assert resolve_display_setting(cfg, "telegram", "tool_progress_compact") is True
    assert resolve_display_setting(cfg, "telegram", "tool_progress_terminal_blocks") is False
    assert resolve_display_setting(cfg, "slack", "tool_progress_terminal_blocks") is True
    assert resolve_display_setting({}, "telegram", "tool_progress_path_chars") == 30
