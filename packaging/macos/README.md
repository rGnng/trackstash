# macOS Packaging

M6 provides an ad-hoc signed PyInstaller build and DMG:

```bash
./packaging/macos/build_dmg.sh
```

The script:

1. installs pinned dependencies with `uv sync --frozen`;
2. builds `dist/TrackStash.app` with `trackstash.spec`;
3. signs the bundle ad-hoc with `codesign`;
4. creates `dist/TrackStash.dmg` with `hdiutil`.

Smoke test the bundled executable:

```bash
QT_QPA_PLATFORM=offscreen \
  dist/TrackStash.app/Contents/MacOS/TrackStash \
  --smoke-test --no-default-library --database /tmp/trackstash-bundle.sqlite
```

## Public release checklist

- Replace ad-hoc signing with a Developer ID Application certificate.
- Enable the hardened runtime and sign nested frameworks and helpers.
- Notarize with `notarytool` and staple the ticket.
- Verify on a clean macOS 13+ machine.
- Publish the corresponding GPL source archive alongside the DMG.
- Include `LICENSE`, `THIRD_PARTY_NOTICES.md`, and dependency notices in the
  release notes or disk image.
