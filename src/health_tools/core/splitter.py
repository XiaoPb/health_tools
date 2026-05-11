"""数据分割模块"""

from pathlib import Path
from typing import List, Optional, Union

import pandas as pd

from health_tools.models.rules import ChipRule
from health_tools.utils.csv_handler import CSVHandler


def split_by_column_value(
    df: pd.DataFrame,
    column: Union[str, int],
    value: Union[int, float] = 0,
) -> List[pd.DataFrame]:
    """
    按指定列值分割数据（当列值等于指定值时开始新段）

    Args:
        df: DataFrame
        column: 列名或列索引
        value: 分割值

    Returns:
        分割后的DataFrame列表
    """
    if isinstance(column, int):
        col_data = df.iloc[:, column]
    else:
        col_data = df[column]

    split_indices = col_data[col_data == value].index.tolist()

    if not split_indices:
        return [df]

    dfs = []
    for i, start_idx in enumerate(split_indices):
        if i < len(split_indices) - 1:
            end_idx = split_indices[i + 1]
            dfs.append(df.loc[start_idx : end_idx - 1].reset_index(drop=True))
        else:
            dfs.append(df.loc[start_idx:].reset_index(drop=True))

    return dfs


def split_by_size(
    df: pd.DataFrame,
    size: int,
) -> List[pd.DataFrame]:
    """
    按行数分割数据

    Args:
        df: DataFrame
        size: 每段行数

    Returns:
        分割后的DataFrame列表
    """
    if size <= 0:
        return [df]

    dfs = []
    for i in range(0, len(df), size):
        dfs.append(df.iloc[i : i + size].reset_index(drop=True))

    return dfs


def split_by_time(
    df: pd.DataFrame,
    time_column: Union[str, int],
    seconds: float,
    format: str = "%Y-%m-%d %H:%M:%S.%f",
) -> List[pd.DataFrame]:
    """
    按时间分割数据

    Args:
        df: DataFrame
        time_column: 时间列名或列索引
        seconds: 每段时间（秒）
        format: 时间格式

    Returns:
        分割后的DataFrame列表
    """
    if isinstance(time_column, int):
        time_data = df.iloc[:, time_column]
    else:
        time_data = df[time_column]

    try:
        times = pd.to_datetime(time_data, format=format)
    except Exception:
        return [df]

    if times.isna().all():
        return [df]

    dfs = []
    start_time = times.iloc[0]
    current_df_indices = [0]

    for i in range(1, len(times)):
        if (times.iloc[i] - start_time).total_seconds() >= seconds:
            dfs.append(df.iloc[current_df_indices[0] : i].reset_index(drop=True))
            current_df_indices = [i]
            start_time = times.iloc[i]
        else:
            current_df_indices.append(i)

    if current_df_indices:
        dfs.append(df.iloc[current_df_indices[0] :].reset_index(drop=True))

    return dfs


class DataSplitter:
    """数据分割器"""

    def __init__(self, chip_rule: Optional[ChipRule] = None):
        self.chip_rule = chip_rule
        self.csv_handler = CSVHandler(chip_rule)

    def split_file(
        self,
        input_file: Union[str, Path],
        output_dir: Union[str, Path],
        by_column: Optional[str] = None,
        column_value: Union[int, float] = 0,
        by_size: Optional[int] = None,
        by_time: Optional[float] = None,
        time_column: Optional[str] = None,
        verbose: bool = False,
    ) -> List[Path]:
        """
        分割文件

        Args:
            input_file: 输入文件
            output_dir: 输出目录
            by_column: 按列分割的列名
            column_value: 分割值
            by_size: 按行数分割
            by_time: 按时间分割（秒）
            time_column: 时间列名
            verbose: 详细输出

        Returns:
            输出文件路径列表
        """
        input_file = Path(input_file)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        info, df = self.csv_handler.read(input_file)

        if df.empty:
            return []

        if by_column:
            dfs = split_by_column_value(df, by_column, column_value)
        elif by_size:
            dfs = split_by_size(df, by_size)
        elif by_time and time_column:
            dfs = split_by_time(df, time_column, by_time)
        else:
            dfs = [df]

        output_files = []
        base_name = input_file.stem

        for i, split_df in enumerate(dfs):
            if split_df.empty:
                continue

            output_file = output_dir / f"{base_name}_{i + 1:04d}.csv"
            self.csv_handler.write(output_file, split_df, info)
            output_files.append(output_file)

            if verbose:
                print(f"  {output_file.name}: {len(split_df)} rows")

        return output_files

    def split_directory(
        self,
        input_dir: Union[str, Path],
        output_dir: Union[str, Path],
        by_column: Optional[str] = None,
        column_value: Union[int, float] = 0,
        by_size: Optional[int] = None,
        by_time: Optional[float] = None,
        time_column: Optional[str] = None,
        verbose: bool = False,
    ) -> List[Path]:
        """
        分割目录下所有文件

        Args:
            input_dir: 输入目录
            output_dir: 输出目录
            by_column: 按列分割的列名
            column_value: 分割值
            by_size: 按行数分割
            by_time: 按时间分割（秒）
            time_column: 时间列名
            verbose: 详细输出

        Returns:
            输出文件路径列表
        """
        input_dir = Path(input_dir)
        output_dir = Path(output_dir)

        files = list(input_dir.glob("*.csv"))
        all_output_files = []

        for file in files:
            file_output_dir = output_dir / file.stem
            output_files = self.split_file(
                file,
                file_output_dir,
                by_column,
                column_value,
                by_size,
                by_time,
                time_column,
                verbose,
            )
            all_output_files.extend(output_files)

        return all_output_files
