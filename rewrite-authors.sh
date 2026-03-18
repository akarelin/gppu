#!/usr/bin/env bash
set -euo pipefail

# Removes Co-Authored-By: Claude lines from all commits on master and dev.
# WARNING: This rewrites history and requires force-push.

echo "This will rewrite git history on master and dev branches."
echo "All Co-Authored-By: Claude lines will be removed from commit messages."
echo ""
read -p "Continue? [y/N] " -n 1 -r
echo
[[ $REPLY =~ ^[Yy]$ ]] || exit 1

for BRANCH in master dev; do
    echo ""
    echo "=== Rewriting $BRANCH ==="
    git checkout "$BRANCH"
    git pull --ff-only

    FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch -f --msg-filter '
        sed -E "/^[[:space:]]*Co-Authored-By:.*[Cc]laude.*$/d" | sed -e :a -e "/^\n*$/{$d;N;ba;}"
    ' -- --all

    echo "Done rewriting $BRANCH"
done

echo ""
echo "=== Preview ==="
git log --all --oneline --grep="Co-Authored-By" | head -20
echo ""
echo "If the above is empty, all Co-Authored-By lines are removed."
echo ""
echo "To push, run:"
echo "  git push --force origin master dev"
echo ""
echo "To undo:"
echo "  git reflog  # find the old HEADs"
echo "  git reset --hard <old-sha>"
