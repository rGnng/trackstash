"""Command-line entry point for the desktop application."""

from __future__ import annotations

from trackstash.app import run


def main() -> int:
    """Run TrackStash and return the process exit code."""
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
