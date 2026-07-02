from pathlib import Path
from typing import List, Optional


def detect_file_encoding(file_path: Path, read_size: int = 10240) -> str:
    """
    检测文件编码

    Args:
        file_path: 文件路径
        read_size: 读取字节数

    Returns:
        编码名称
    """
    try:
        import chardet

        with open(file_path, "rb") as f:
            raw_data = f.read(read_size)

        result = chardet.detect(raw_data)
        encoding = result.get("encoding", "utf-8")

        if encoding and encoding.lower() in ["gb2312", "gbk", "gb18030"]:
            encoding = "gb18030"

        return encoding or "utf-8"
    except ImportError:
        return "utf-8"
    except Exception:
        return "utf-8"


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

    files: List[Path] = []
    if recursive:
        for ext in extensions:
            files.extend(directory.rglob(f"*{ext}"))
    else:
        for ext in extensions:
            files.extend(directory.glob(f"*{ext}"))

    return sorted(files)
