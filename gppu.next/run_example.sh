#!/usr/bin/env bash
# Runs a gppu.next example with core and every provider on the path: run_example.sh archive --since 3d
here="$(cd "$(dirname "$0")" && pwd)"
paths="$here/core"; for p in "$here"/providers/*/; do paths="$paths:${p%/}"; done
[[ "$OSTYPE" == msys* || "$OSTYPE" == cygwin* ]] && paths="$(cygpath -pw "$paths")"
PYTHONPATH="$paths" exec "${PYTHON:-python}" "$here/examples/$1.py" "${@:2}"
