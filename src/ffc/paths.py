from __future__ import annotations

from pathlib import Path


def path_key(path: Path) -> str:
    return str(path.expanduser().resolve()).casefold()


def ensure_unique_paths(paths: list[Path], description: str) -> None:
    seen: dict[str, Path] = {}
    for path in paths:
        key = path_key(path)
        if key in seen:
            raise ValueError(f"Multiple inputs would write the same {description}: {path}")
        seen[key] = path
