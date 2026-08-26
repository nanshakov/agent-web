from __future__ import annotations

import shutil
from pathlib import Path


def find_codex() -> Path | None:
    """Prefer the standalone install over a non-executable Windows App alias."""
    home = Path.home() / ".codex" / "packages" / "standalone" / "releases"
    if home.exists():
        candidates = sorted(home.glob("*/bin/codex.exe"), reverse=True)
        if candidates:
            return candidates[0]
    command = shutil.which("codex")
    return Path(command) if command else None

