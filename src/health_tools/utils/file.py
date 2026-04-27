from pathlib import Path
from typing import List, Optional


def ensure_dir(path: Path) -> Path:
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
    return path


def find_files(
    directory: Path,
    extensions: Optional[List[str]] = None,
    recursive: bool = False,
) -> List[Path]:
    if not directory.exists():
        return []

    if extensions is None:
        extensions = [".csv", ".log", ".txt"]

    files = []
    if recursive:
        for ext in extensions:
            files.extend(directory.rglob(f"*{ext}"))
    else:
        for ext in extensions:
            files.extend(directory.glob(f"*{ext}"))

    return sorted(files)
