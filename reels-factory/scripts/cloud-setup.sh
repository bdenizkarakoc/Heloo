#!/usr/bin/env bash
# Bulut oturumunda (Claude Code on the web) bağımlılıkları kurar; tekrar çalıştırmak güvenlidir.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pip install -q -r requirements.txt 2>&1 | grep -v "WARNING: Running pip as" || true
[ -x node_modules/.bin/hyperframes ] || npm install --silent
npx hyperframes browser ensure >/dev/null 2>&1 || npx hyperframes browser ensure
npx hyperframes telemetry disable >/dev/null 2>&1 || true
# Önceki bulut çalışmalarının üretim geçmişini geri yükle (konu tekrarını önlemek için)
if [ ! -f projects/_history.json ] && git fetch -q origin reels-videos 2>/dev/null; then
  git show origin/reels-videos:history.json > projects/_history.json 2>/dev/null || rm -f projects/_history.json
fi
python3 scripts/factory.py doctor --offline | tail -1
