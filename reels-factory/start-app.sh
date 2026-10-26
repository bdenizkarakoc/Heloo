#!/usr/bin/env bash
# Reels Fabrikası uygulamasını başlatır ve tarayıcıda açar.
cd "$(dirname "$0")" && exec python3 app/server.py --open
