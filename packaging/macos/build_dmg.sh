#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

uv sync --frozen
rm -rf build dist
uv run pyinstaller --noconfirm --clean packaging/macos/trackstash.spec

APP="$ROOT/dist/TrackStash.app"
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

hdiutil create \
  -volname "TrackStash" \
  -srcfolder "$APP" \
  -ov \
  -format UDZO \
  "$ROOT/dist/TrackStash.dmg"

echo "Built $APP"
echo "Built $ROOT/dist/TrackStash.dmg"
