#!/usr/bin/env bash
# Claude Code kurulumu + girişi (macOS/Linux). Kullanım: bash scripts/install-claude.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
command -v claude >/dev/null || curl -fsSL https://claude.ai/install.sh | bash
claude --version
claude auth status 2>/dev/null | grep -q '"loggedIn": true' || claude auth login
echo "✔ Claude Code hazır; uygulama senaryoları artık Claude Code ile yazar."
