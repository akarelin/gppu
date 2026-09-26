#!/usr/bin/env bash
# Runs a gppu example from this checkout: run_example.sh archive --since 3d
here="$(cd "$(dirname "$0")" && pwd)"
PYTHONPATH="$here" exec "${PYTHON:-python}" "$here/examples/$1.py" "${@:2}"
