#!/usr/bin/env bash
# reels-videos dalındaki inbox/ klasörü: kullanıcının metinleri (GitHub web/mobil ile eklenir).
#   bash scripts/inbox.sh list            # bekleyen .txt/.md dosyalarını listeler
#   bash scripts/inbox.sh get <dosya>     # içeriğini yazdırır
#   bash scripts/inbox.sh done <dosya>    # inbox/done/ altına taşır ve push eder
set -euo pipefail
BR=reels-videos
ROOT=$(git rev-parse --show-toplevel)
git -C "$ROOT" fetch -q origin "$BR" 2>/dev/null || { [ "${1:-}" = list ] && exit 0; echo "dal yok"; exit 1; }
case "${1:-list}" in
  list) git -C "$ROOT" ls-tree --name-only "origin/$BR" inbox/ 2>/dev/null | grep -E '\.(txt|md)$' | grep -v '^inbox/done/' || true ;;
  get)  git -C "$ROOT" show "origin/$BR:$2" ;;
  done)
    WT=$(mktemp -d); trap 'git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || rm -rf "$WT"' EXIT
    git -C "$ROOT" worktree add -q -B "$BR" "$WT" "origin/$BR"
    mkdir -p "$WT/inbox/done"; git -C "$WT" mv "$2" "inbox/done/$(date +%Y%m%d-%H%M)-$(basename "$2")"
    git -C "$WT" commit -qm "Gelen kutusu: $(basename "$2") işlendi"
    for i in 1 2 3 4; do git -C "$WT" push -q origin "$BR" && break || sleep $((2**i)); done ;;
esac
