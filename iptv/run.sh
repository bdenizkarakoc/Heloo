#!/usr/bin/env sh
# Heloo TV (Linux/macOS): libmpv sistemden (apt install libmpv2 / brew install mpv). RTX VSR yalnızca Windows'ta.
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt || exit 1
fi
exec .venv/bin/python -m helootv "$@"
