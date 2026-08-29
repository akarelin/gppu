#!/bin/sh
# Install gppu statusline for Claude Code on a Debian/Linux host.
# Run on the target host; assumes Claude Code is already installed.

mkdir -p ~/.local/bin

url=$(curl -fsSL "https://api.github.com/repos/akarelin/gppu/releases?per_page=100" | grep -oP '"browser_download_url":\s*"\K[^"]*statusline-linux-amd64' | head -1)
tag=$(echo "$url" | sed 's|.*/download/||; s|/statusline-linux-amd64$||')
curl -fsSL -o ~/.local/bin/statusline "$url"
chmod +x ~/.local/bin/statusline

python3 - <<'EOF'
import json, os
p = os.path.expanduser("~/.claude/settings.json")
s = json.load(open(p)) if os.path.exists(p) else {}
s["statusLine"] = {"type": "command", "command": os.path.expanduser("~/.local/bin/statusline")}
json.dump(s, open(p, "w"), indent=2)
EOF

echo "statusline $tag installed"
