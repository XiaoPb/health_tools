"""带内容 revision 的原子文本文件工具。"""

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Optional, Tuple


def content_revision(data: bytes) -> str:
    """返回原始文件字节的稳定 SHA-256 revision。"""
    return hashlib.sha256(data).hexdigest()


def read_text_revision(path: Path) -> Tuple[str, str]:
    """读取 UTF-8 文本及其基于原始字节的 revision。"""
    data = path.read_bytes()
    return data.decode("utf-8"), content_revision(data)


def current_revision(path: Path) -> Optional[str]:
    """读取当前 revision；文件不存在时返回 None。"""
    if not path.exists():
        return None
    return content_revision(path.read_bytes())


def atomic_write_text(path: Path, source: str) -> None:
    """在目标目录中写临时文件，并原子替换目标文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(source)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
