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


def test_supported_claude_tools_have_icons():
    names = {
        "Agent", "Artifact", "AskUserQuestion", "Bash",
        "CronCreate", "CronDelete", "CronList", "Edit",
        "EnterPlanMode", "EnterWorktree", "ExitPlanMode", "Glob", "Grep",
        "ListAgents", "Monitor", "PowerShell", "PushNotification", "Read",
        "ScheduleWakeup", "SendFeedback", "SendMessage", "SendUserFile", "Skill",
        "StructuredOutput", "TaskCreate", "TaskList", "TaskOutput", "TaskStop",
        "TaskUpdate", "TodoWrite", "ToolSearch", "WebFetch", "WebSearch",
        "Workflow", "Write",
    }
    assert [name for name in sorted(names) if _tool_icon(name) == name] == []


def test_unknown_tool_name_remains_visible():
    assert _tool_icon("Grag") == "Grag"
