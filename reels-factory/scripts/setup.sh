#!/usr/bin/env bash
# Reels Factory kurulumu: Python + Node bağımlılıkları, render tarayıcısı, .env şablonu.
# Kullanım (reels-factory/ klasöründen): bash scripts/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

need() { command -v "$1" >/dev/null 2>&1 || { echo "✖ '$1' bulunamadı: $2"; exit 1; }; }
need python3 "Python 3.10+ kurun"
need ffmpeg "FFmpeg kurun (macOS: brew install ffmpeg, Ubuntu: sudo apt install ffmpeg)"
need node "Node.js 22+ kurun (https://nodejs.org)"
node -e 'process.exit(parseInt(process.versions.node) >= 22 ? 0 : 1)' || { echo "✖ Node.js 22+ gerekli"; exit 1; }

echo "▶ Python bağımlılıkları"
python3 -m pip install -r requirements.txt

echo "▶ Node bağımlılıkları (HyperFrames, GSAP)"
npm install

echo "▶ HyperFrames render tarayıcısı (Chrome Headless Shell)"
npx hyperframes browser ensure

# HyperFrames anonim kullanım verisi toplar; gizlilik için kapatıyoruz. Açmak için: npx hyperframes telemetry enable
npx hyperframes telemetry disable >/dev/null 2>&1 || true

if [ ! -f .env ]; then
  cp .env.example .env
  echo "▶ .env oluşturuldu (isteğe bağlı API anahtarlarını buraya yazın)"
fi

python3 scripts/factory.py doctor
