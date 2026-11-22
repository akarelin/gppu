"""Transcript parsing: what counts as a user turn."""

import json

from statusline.cache import _is_user_prompt, _parse_from_offset, transcript_stats_cached


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


def test_a_line_being_written_is_read_next_time(tmp_path):
    done = {"type": "user", "message": {"content": "first question"}}
    partial = json.dumps({"type": "user", "message": {"content": "second question"}})
    path = tmp_path / "t.jsonl"
    path.write_bytes((json.dumps(done) + "\n" + partial[:20]).encode())

    _, counts, _, offset = _parse_from_offset(str(path), 0)
    assert counts["user"] == 1
    assert offset == len(json.dumps(done)) + 1

    path.write_bytes((json.dumps(done) + "\n" + partial + "\n").encode())
    _, counts, _, end = _parse_from_offset(str(path), offset)
    assert counts["user"] == 1
    assert end == path.stat().st_size


def test_a_rewritten_smaller_file_is_read_from_the_start(tmp_path):
    line = json.dumps({"type": "user", "message": {"content": "question"}}) + "\n"
    path = tmp_path / "t.jsonl"
    path.write_bytes((line * 3).encode())
    _, counts, *_ = transcript_stats_cached(str(path), 0)
    assert counts["user"] == 3

    path.write_bytes((line).encode())
    _, counts, *_ = transcript_stats_cached(str(path), 0)
    assert counts["user"] == 1
