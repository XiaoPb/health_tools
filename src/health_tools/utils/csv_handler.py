"""统一CSV读写模块"""

from io import StringIO
from pathlib import Path
from typing import Optional, Tuple, Union

import pandas as pd

from health_tools.models.rules import ChipRule
from health_tools.utils.file import detect_file_encoding


class CSVHandler:
    """统一CSV读写处理器"""

    def __init__(self, chip_rule: Optional[ChipRule] = None):
        self.chip_rule = chip_rule

    def read(
        self,
        file_path: Union[str, Path],
        auto_detect_encoding: bool = True,
    ) -> Tuple[str, pd.DataFrame]:
        """
        根据chip规则读取CSV文件

        Args:
            file_path: 文件路径
            auto_detect_encoding: 是否自动检测编码

        Returns:
            (info, df): 信息行和DataFrame
        """
        file_path = Path(file_path)

        if auto_detect_encoding:
            encoding = detect_file_encoding(file_path)
        else:
            encoding = self.chip_rule.encoding if self.chip_rule else "utf-8"

        with open(file_path, "r", encoding=encoding) as f:
            lines = f.readlines()

        if not lines:
            return "", pd.DataFrame()

        info_row = self.chip_rule.info_row if self.chip_rule else 0
        header_row = self.chip_rule.header_row if self.chip_rule else 1
        data_start_row = self.chip_rule.data_start_row if self.chip_rule else 2
        delimiter = self.chip_rule.delimiter if self.chip_rule else ","

        info = ""
        if info_row > 0 and info_row <= len(lines):
            info = lines[info_row - 1].strip()

        header = None
        if header_row > 0 and header_row <= len(lines):
            header = [h.strip() for h in lines[header_row - 1].strip().split(delimiter)]

        data_start_idx = data_start_row - 1 if data_start_row > 0 else 0
        data_lines = lines[data_start_idx:]

        if not data_lines:
            return info, pd.DataFrame()

        if header:
            df = pd.read_csv(
                StringIO("".join(data_lines)),
                header=None,
                names=header,
                delimiter=delimiter,
                low_memory=False,
            )
        else:
            df = pd.read_csv(
                StringIO("".join(data_lines)),
                header=None,
                delimiter=delimiter,
                low_memory=False,
            )

        return info, df

    def write(
        self,
        file_path: Union[str, Path],
        df: pd.DataFrame,
        info: Optional[str] = None,
    ) -> None:
        """
        根据chip规则写入CSV文件

        Args:
            file_path: 文件路径
            df: DataFrame
            info: 信息行内容
        """
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
        """
        读取CSV文件并只保留指定列

        Args:
            file_path: 文件路径
            columns: 要保留的列名列表
            auto_detect_encoding: 是否自动检测编码

        Returns:
            (info, df): 信息行和DataFrame
        """
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
    """
    便捷函数：读取CSV文件

    Args:
        file_path: 文件路径
        chip_rule: 芯片规则
        auto_detect_encoding: 是否自动检测编码

    Returns:
        (info, df): 信息行和DataFrame
    """
    handler = CSVHandler(chip_rule)
    return handler.read(file_path, auto_detect_encoding)


def write_csv(
    file_path: Union[str, Path],
    df: pd.DataFrame,
    chip_rule: Optional[ChipRule] = None,
    info: Optional[str] = None,
) -> None:
    """
    便捷函数：写入CSV文件

    Args:
        file_path: 文件路径
        df: DataFrame
        chip_rule: 芯片规则
        info: 信息行内容
    """
    handler = CSVHandler(chip_rule)
    handler.write(file_path, df, info)


def read_csv_df(
    file_path: Union[str, Path],
    chip_rule: Optional[ChipRule] = None,
) -> pd.DataFrame:
    """读取CSV返回DataFrame（忽略info行）"""
    _, df = read_csv(file_path, chip_rule)
    return df
