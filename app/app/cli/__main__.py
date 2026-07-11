"""Module entry point so ``python -m app.cli`` mirrors the ``cosci`` script."""

from __future__ import annotations

from app.cli.main import main

if __name__ == "__main__":
    raise SystemExit(main())
