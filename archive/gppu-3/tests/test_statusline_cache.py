"""Transcript parsing: what counts as a user turn."""

import json

from statusline.cache import _is_user_prompt, _parse_from_offset


def test_tool_results_are_not_user_turns():
    assert _is_user_prompt({"content": "update the statusline"})
    assert _is_user_prompt({"content": [{"type": "text", "text": "hi"}]})
    assert not _is_user_prompt({"content": [{"type": "tool_result", "content": "ok"}]})
    assert not _is_user_prompt({"content": ""})
    assert not _is_user_prompt(None)


def test_parse_counts_prompts_not_tool_traffic(tmp_path):
    entries = [
        {"type": "user", "isMeta": True, "version": "2.1.0", "cwd": "/x",
         "message": {"content": "<meta>"}},
        {"type": "user", "message": {"content": "first question"}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "..."}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "..."}]}},
        {"type": "user", "message": {"content": [{"type": "text", "text": "second question"}]}},
    ]
    path = tmp_path / "t.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")

    tools, counts, meta, offset = _parse_from_offset(str(path), 0)
    assert counts["user"] == 2
    assert counts["assistant"] == 2
    assert tools == {"Read": 2}
    assert meta["version"] == "2.1.0"
    assert offset > 0
