from __future__ import annotations

from pathlib import Path


class StoragePathError(ValueError):
    pass


def write_bytes_under(root: Path, relative_path: str | Path, content: bytes) -> Path:
    root = root.resolve()
    path = (root / relative_path).resolve()
    if root != path and root not in path.parents:
        raise StoragePathError(f"Refusing to write outside storage root: {relative_path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
    return path
