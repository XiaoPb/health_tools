"""统一CSV读写模块"""

from pathlib import Path
from typing import List, Optional, Tuple, Union

import pandas as pd

from health_tools.models.rules import ChipRule
from health_tools.utils.file import detect_file_encoding

MAX_CHUNK_SIZE = 50000


class CSVHandler:
    """统一CSV读写处理器"""

    def __init__(self, chip_rule: Optional[ChipRule] = None):
        self.chip_rule = chip_rule

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
    ) -> Tuple[str, pd.DataFrame]:
        file_path = Path(file_path)
        encoding = self._detect_encoding(file_path, auto_detect_encoding)

        info_row = self.chip_rule.info_row if self.chip_rule else 0
        header_row = self.chip_rule.header_row if self.chip_rule else 1
        data_start_row = self.chip_rule.data_start_row if self.chip_rule else 2
        delimiter = self.chip_rule.delimiter if self.chip_rule else ","

        info = self._read_info_line(file_path, info_row, encoding)

        if header_row > 0 and header_row < data_start_row:
            skiprows = self._build_skiprows(header_row, data_start_row)
            chunks = pd.read_csv(
                file_path,
                header=0,
                skiprows=skiprows if skiprows else None,
                delimiter=delimiter,
                encoding=encoding,
                chunksize=MAX_CHUNK_SIZE,
            )
            df = pd.concat(chunks, ignore_index=True)
        elif header_row > 0:
            chunks = pd.read_csv(
                file_path,
                header=header_row - 1,
                delimiter=delimiter,
                encoding=encoding,
                chunksize=MAX_CHUNK_SIZE,
            )
            df = pd.concat(chunks, ignore_index=True)
        else:
            chunks = pd.read_csv(
                file_path,
                header=None,
                skiprows=data_start_row - 1 if data_start_row > 1 else None,
                delimiter=delimiter,
                encoding=encoding,
                chunksize=MAX_CHUNK_SIZE,
            )
            df = pd.concat(chunks, ignore_index=True)

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
                f.write(info + "\n")
            df.to_csv(f, index=False, sep=delimiter)

    def read_with_columns(
        self,
        file_path: Union[str, Path],
        columns: Optional[list] = None,
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
