#!/usr/bin/env bash
# Bulut oturumunda (Claude Code on the web) bağımlılıkları kurar; tekrar çalıştırmak güvenlidir.
# Sistem Python'larının paket uyuşmazlıklarından etkilenmemek için kendi sanal ortamını (.venv) kurar.
# Sonraki bütün komutlar: ./rf <komut>   (ör. ./rf selftest, ./rf produce <görev>)
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  PY=""
  for c in python3.13 python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c "import venv, ensurepip" >/dev/null 2>&1; then PY="$c"; break; fi
  done
  [ -n "$PY" ] || { echo "✖ venv destekli Python bulunamadı"; exit 1; }
  "$PY" -m venv .venv
fi
.venv/bin/python -m pip install -q --upgrade pip >/dev/null 2>&1 || true
.venv/bin/python -m pip install -q -r requirements.txt
[ -x node_modules/.bin/hyperframes ] || npm install --silent
npx hyperframes browser ensure >/dev/null 2>&1 || npx hyperframes browser ensure
npx hyperframes telemetry disable >/dev/null 2>&1 || true
# Önceki bulut çalışmalarının üretim geçmişini geri yükle (konu tekrarını önlemek için)
if [ ! -f projects/_history.json ] && git fetch -q origin reels-videos 2>/dev/null; then
  git show origin/reels-videos:history.json > projects/_history.json 2>/dev/null || rm -f projects/_history.json
fi
./rf doctor --offline | tail -1
