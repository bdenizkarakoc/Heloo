#!/usr/bin/env bash
# Videoyu GitHub'daki ayrı 'reels-videos' dalına yükler ve bağlantıyı yazdırır.
# Kullanım: bash scripts/deliver.sh <video.mp4> [kapak.jpg] [paylasim.txt] [altyazi.srt]
set -euo pipefail
BR=reels-videos
ROOT=$(git rev-parse --show-toplevel)
REMOTE=$(git -C "$ROOT" remote get-url origin)
SLUG=$(echo "$REMOTE" | sed -E 's#.*github\.com[:/]+##; s#\.git$##')
DAY=$(date +%Y-%m-%d)
WT=$(mktemp -d)
cleanup() { git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || rm -rf "$WT"; }
trap cleanup EXIT
if git -C "$ROOT" fetch -q origin "$BR" 2>/dev/null; then
  git -C "$ROOT" worktree add -q -B "$BR" "$WT" "origin/$BR"
else
  git -C "$ROOT" worktree add -q --detach "$WT"
  git -C "$WT" checkout -q --orphan "$BR"
  git -C "$WT" rm -rq --cached . && find "$WT" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
  printf '# Reels videoları\n\nReels Fabrikası tarafından üretilen videolar (tarih klasörlerinde).\n' > "$WT/README.md"
fi
mkdir -p "$WT/videos/$DAY"
for f in "$@"; do [ -f "$f" ] && cp "$f" "$WT/videos/$DAY/"; done
# Üretim geçmişi (konu/müzik tekrarını önler) bulut oturumları arasında burada saklanır
HIST="$ROOT/reels-factory/projects/_history.json"
[ -f "$HIST" ] && cp "$HIST" "$WT/history.json"
git -C "$WT" add -A
git -C "$WT" commit -qm "Video: $(basename "$1") ($DAY)" || true
for i in 1 2 3 4; do git -C "$WT" push -q -u origin "$BR" && break || sleep $((2**i)); done
echo "https://github.com/$SLUG/blob/$BR/videos/$DAY/$(basename "$1")"
