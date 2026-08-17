"""Tool breakdown: icons, merging, and unbounded names."""

import re
from collections import Counter

from statusline.status_line import _ftop_tools, _tool_icon


def _plain(s):
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


def test_mcp_names_do_not_reach_the_line():
    assert _tool_icon("mcp__plugin_openviking-memory_openviking__health") == "🔌"
    assert _tool_icon("Bash") == "❯"
    assert _tool_icon("SomeNewTool") == "SomeNewTool"


def test_shared_icons_merge_into_one_entry():
    tools = Counter({
        "Bash": 100, "PowerShell": 8,
        "mcp__a__one": 3, "mcp__b__two": 2,
        "Read": 5,
    })
    assert _plain(_ftop_tools(tools)) == "❯ 108 🔌 5 📖 5"
