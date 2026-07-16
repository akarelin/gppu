#!/bin/sh
# Install gppu statusline for Claude Code on a Debian/Linux host.
# Run on the target host; assumes Claude Code is already installed and git SSH auth to github.com works.

mkdir -p ~/.local/bin ~/.config/statusline

tag=$(curl -fsSL "https://api.github.com/repos/akarelin/gppu/releases?per_page=100" \
  | grep -oP '"tag_name":\s*"\Ksl-[^"]+' | head -1)
curl -fsSL -o ~/.local/bin/statusline \
  "https://github.com/akarelin/gppu/releases/download/$tag/statusline-linux-amd64"
chmod +x ~/.local/bin/statusline

git clone --depth 1 git@github.com:akarelin/dotfiles.git /tmp/dotfiles-statusline
cp /tmp/dotfiles-statusline/private_dot_config/statusline/*.yaml ~/.config/statusline/
rm -rf /tmp/dotfiles-statusline

python3 - <<'EOF'
import json, os
p = os.path.expanduser("~/.claude/settings.json")
s = json.load(open(p)) if os.path.exists(p) else {}
s["statusLine"] = {"type": "command", "command": os.path.expanduser("~/.local/bin/statusline")}
json.dump(s, open(p, "w"), indent=2)
EOF

echo "statusline $tag installed"
