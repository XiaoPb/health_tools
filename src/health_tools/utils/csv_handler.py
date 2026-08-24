"""统一CSV读写模块"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from health_tools.models.rules import ChipRule
from health_tools.utils.columns import expand_columns
from health_tools.utils.file import detect_file_encoding

TRAILING_ZERO_SCAN_ROWS = 500

_CSV_INJECTION_PATTERN = re.compile(r"^[=+\-@\t\r]")


def _downcast_integer_columns(df: pd.DataFrame) -> pd.DataFrame:
    """在不改变数值范围的前提下压缩整型列，降低大 CSV 的常驻内存。"""
    int32_min, int32_max = np.iinfo(np.int32).min, np.iinfo(np.int32).max
    dtypes = {}
    for column in df.select_dtypes(include=["integer"]).columns:
        series = df[column]
        if series.empty:
            continue
        if series.min() >= int32_min and series.max() <= int32_max:
            dtypes[column] = np.int32
    return df.astype(dtypes, copy=False) if dtypes else df


def _sanitize_csv_cell(value: str) -> str:
    """防止CSV公式注入（给危险前缀加单引号）"""
    if value and _CSV_INJECTION_PATTERN.match(value):
        return "'" + value
    return value


class CSVHandler:
    """统一CSV读写处理器"""

    def __init__(self, chip_rule: Optional[ChipRule] = None):
        self.chip_rule = chip_rule
        self.excluded_columns: List[str] = []

    @staticmethod
    def _trailing_zero_columns(
        read_kwargs: Dict[str, object], protected_columns: List[str]
    ) -> List[str]:
        protected = set(protected_columns)
        families: Dict[str, List[Tuple[int, str]]] = {}
        last_active: Dict[str, int] = {}
        sample = pd.read_csv(**read_kwargs, nrows=TRAILING_ZERO_SCAN_ROWS)
        for column in sample.columns:
            if column in protected:
                continue
            matched = re.match(r"^(.*?)(\d+)$", str(column))
            if matched:
                families.setdefault(matched.group(1), []).append((int(matched.group(2)), column))

        for prefix, columns in families.items():
            for index, column in columns:
                if index <= last_active.get(prefix, -1):
                    continue
                series = sample[column]
                minimum = series.min(skipna=True)
                maximum = series.max(skipna=True)
                if pd.notna(minimum) and (minimum != 0 or maximum != 0):
                    last_active[prefix] = index

        excluded = []
        for prefix, columns in families.items():
            final_index = last_active.get(prefix, -1)
            excluded.extend(column for index, column in columns if index > final_index)
        return excluded

    def _detect_encoding(self, file_path: Path, auto_detect: bool) -> str:
        if auto_detect:
            encoding = detect_file_encoding(file_path)
            if not encoding or encoding.lower() == "ascii":
                return "utf-8"
            return encoding
        return self.chip_rule.encoding if self.chip_rule else "utf-8"

    def _read_info_line(self, file_path: Path, info_row: int, encoding: str) -> str:
        if info_row <= 0:
            return ""
        with open(file_path, "r", encoding=encoding) as f:
            for i, line in enumerate(f, 1):
                if i == info_row:
                    return line.strip()
        return ""

    def _build_skiprows(self, header_row: int, data_start_row: int) -> List[int]:
        """构建需要跳过的行号列表（0-based）"""
        skip = []
        for r in range(data_start_row - 1):
            if r != header_row - 1:
                skip.append(r)
        return skip

    def read(
        self,
        file_path: Union[str, Path],
        auto_detect_encoding: bool = True,
        *,
        trim_trailing_zero: bool = False,
        protected_columns: Optional[List[str]] = None,
    ) -> Tuple[str, pd.DataFrame]:
        file_path = Path(file_path)
        encoding = self._detect_encoding(file_path, auto_detect_encoding)

        info_row = self.chip_rule.info_row if self.chip_rule else 0
        header_row = self.chip_rule.header_row if self.chip_rule else 1
        data_start_row = self.chip_rule.data_start_row if self.chip_rule else 2
        delimiter = self.chip_rule.delimiter if self.chip_rule else ","

        info = self._read_info_line(file_path, info_row, encoding)

        read_kwargs = {
            "filepath_or_buffer": file_path,
            "index_col": False,
            "delimiter": delimiter,
            "encoding": encoding,
        }
        if self.chip_rule and self.chip_rule.columns:
            read_kwargs["dtype"] = {
                column: np.int32 for column in expand_columns(self.chip_rule.columns)
            }
        if header_row > 0 and header_row < data_start_row:
            read_kwargs.update(
                {
                    "header": 0,
                    "skiprows": self._build_skiprows(header_row, data_start_row) or None,
                }
            )
        elif header_row > 0:
            read_kwargs["header"] = header_row - 1
        else:
            read_kwargs.update(
                {
                    "header": None,
                    "skiprows": data_start_row - 1 if data_start_row > 1 else None,
                }
            )
        self.excluded_columns = []
        if trim_trailing_zero:
            self.excluded_columns = self._trailing_zero_columns(
                read_kwargs, protected_columns or []
            )
            excluded = set(self.excluded_columns)
            read_kwargs["usecols"] = lambda column: column not in excluded
        df = _downcast_integer_columns(pd.read_csv(**read_kwargs))

        return info, df

    def write(
        self,
        file_path: Union[str, Path],
        df: pd.DataFrame,
        info: Optional[str] = None,
    ) -> None:
        file_path = Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        encoding = self.chip_rule.encoding if self.chip_rule else "utf-8"
        delimiter = self.chip_rule.delimiter if self.chip_rule else ","
        info_row = self.chip_rule.info_row if self.chip_rule else 0

        with open(file_path, "w", encoding=encoding, newline="") as f:
            if info_row > 0 and info:
                f.write(_sanitize_csv_cell(info) + "\n")
            df.to_csv(f, index=False, sep=delimiter)

    def read_with_columns(
        self,
        file_path: Union[str, Path],
        columns: Optional[List] = None,
        auto_detect_encoding: bool = True,
    ) -> Tuple[str, pd.DataFrame]:
        info, df = self.read(file_path, auto_detect_encoding)

        if columns and not df.empty:
            existing_cols = [c for c in columns if c in df.columns]
            if existing_cols:
                df = df[existing_cols]

        return info, df


def read_csv(
    file_path: Union[str, Path],
    chip_rule: Optional[ChipRule] = None,
    auto_detect_encoding: bool = True,
) -> Tuple[str, pd.DataFrame]:
    handler = CSVHandler(chip_rule)
    return handler.read(file_path, auto_detect_encoding)


def write_csv(
    file_path: Union[str, Path],
    df: pd.DataFrame,
    chip_rule: Optional[ChipRule] = None,
    info: Optional[str] = None,
) -> None:
    handler = CSVHandler(chip_rule)
    handler.write(file_path, df, info)


def read_csv_df(
    file_path: Union[str, Path],
    chip_rule: Optional[ChipRule] = None,
) -> pd.DataFrame:
    """读取CSV返回DataFrame（忽略info行）"""
    _, df = read_csv(file_path, chip_rule)
    return df
