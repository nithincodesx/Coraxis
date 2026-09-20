"""``python -m coraxis`` — delegates to the CLI."""

from __future__ import annotations

from coraxis.cli.main import main

__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main())
