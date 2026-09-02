"""离线跑库CSV输入预检。"""

import csv
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from health_tools.models.rules import ChipRule

MAX_PREVIEW_LINES = 3
REF_RESULT_COLUMNS = {f"REF_RESULT{index}" for index in range(16)}


class OfflineInputFilterError(RuntimeError):
    """离线输入过滤无法安全完成。"""


@dataclass(frozen=True)
class MovedOfflineInput:
    """已移动的不合规CSV。"""

    source: Path
    target: Path
    reason: str


@dataclass
class OfflineInputFilterResult:
    """离线输入过滤汇总。"""

    scanned_count: int = 0
    accepted_count: int = 0
    backup_dir: Optional[Path] = None
    moved_files: List[MovedOfflineInput] = field(default_factory=list)

    @property
    def moved_count(self) -> int:
        return len(self.moved_files)


def _iter_csv_files(input_dir: Path) -> List[Path]:
    return sorted(
        path for path in input_dir.rglob("*") if path.is_file() and path.suffix.lower() == ".csv"
    )


def _read_header(file_path: Path, chip_rule: ChipRule) -> Tuple[Optional[List[str]], str]:
    try:
        with open(file_path, "r", encoding=chip_rule.encoding, newline="") as file:
            lines = []
            for _ in range(MAX_PREVIEW_LINES):
                line = file.readline()
                if line == "":
                    break
                lines.append(line)
    except UnicodeError:
        return None, "文件编码错误"
    except OSError as exc:
        return None, f"文件读取失败: {exc}"

    if chip_rule.header_row <= 0 or chip_rule.header_row > len(lines):
        return None, "文件行数不足"

    try:
        header = next(
            csv.reader(
                [lines[chip_rule.header_row - 1]],
                delimiter=chip_rule.delimiter,
                strict=True,
            )
        )
    except (csv.Error, StopIteration):
        return None, "CSV表头解析失败"

    if header:
        header[0] = header[0].lstrip("\ufeff")
    return header, ""


def _headers_match(expected_header: List[str], header: Optional[List[str]]) -> bool:
    """比较离线输入表头，完整金标列仅放宽其列名。"""
    if header is None or len(header) != len(expected_header):
        return False

    ref_columns = [column for column in expected_header if column.startswith("REF_RESULT")]
    allow_ref_names = len(ref_columns) == 16 and set(ref_columns) == REF_RESULT_COLUMNS

    for expected, actual in zip(expected_header, header):
        if allow_ref_names and expected in REF_RESULT_COLUMNS:
            if not isinstance(actual, str) or not actual.strip():
                return False
            continue
        if actual != expected:
            return False
    return True


def _unique_target(target: Path) -> Path:
    if not target.exists():
        return target
    index = 1
    while True:
        candidate = target.with_name(f"{target.stem}_{index}{target.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def move_offline_input(source: Path, input_dir: Path, reason: str) -> MovedOfflineInput:
    """将不合规输入移动到同级 ``<input>_mv`` 目录并返回移动记录。"""
    input_dir = Path(input_dir).resolve()
    source = Path(source).resolve()
    relative_source = source.relative_to(input_dir)
    backup_dir = input_dir.parent / f"{input_dir.name}_mv"
    target = _unique_target(backup_dir / relative_source)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
    except OSError as exc:
        raise OfflineInputFilterError(f"移动不合规文件失败: {source} -> {target}: {exc}") from exc
    return MovedOfflineInput(source, target, reason)


def filter_offline_inputs(input_dir: Path, chip_rule: ChipRule) -> OfflineInputFilterResult:
    """严格校验CSV表头，并将不合规文件移到同级备份目录。"""
    input_dir = input_dir.resolve()
    backup_dir = input_dir.parent / f"{input_dir.name}_mv"
    result = OfflineInputFilterResult(backup_dir=backup_dir)
    expected_header = list(chip_rule.columns)

    for source in _iter_csv_files(input_dir):
        result.scanned_count += 1
        header, reason = _read_header(source, chip_rule)
        if _headers_match(expected_header, header):
            result.accepted_count += 1
            continue
        if not reason:
            reason = "表头与芯片规则不一致"

        result.moved_files.append(move_offline_input(source, input_dir, reason))

    return result
