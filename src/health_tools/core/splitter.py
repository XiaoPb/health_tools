"""数据分割模块"""

from pathlib import Path
from typing import List, Optional, Union

import numpy as np
import pandas as pd

from health_tools.models.rules import ChipRule
from health_tools.utils.csv_handler import CSVHandler
from health_tools.utils.errors import (
    REASON_BAD_FORMAT,
    REASON_EMPTY_FILE,
    REASON_MISSING_COLUMN,
    REASON_PROCESS_FAILED,
    classify_exception,
)
from health_tools.utils.progress import progress_track
from health_tools.utils.reporting import STATUS_FAIL, STATUS_SKIP, FileResult, ResultCollector


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

    positional_indices = np.flatnonzero(col_data.to_numpy() == value).tolist()

    if not positional_indices:
        return [df]

    dfs = []
    if positional_indices[0] > 0:
        dfs.append(df.iloc[: positional_indices[0]].reset_index(drop=True))

    for i, pos in enumerate(positional_indices):
        if i < len(positional_indices) - 1:
            end_pos = positional_indices[i + 1]
            dfs.append(df.iloc[pos:end_pos].reset_index(drop=True))
        else:
            dfs.append(df.iloc[pos:].reset_index(drop=True))

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

    elapsed = (times - times.iloc[0]).dt.total_seconds().to_numpy()
    group_ids = np.floor(elapsed / seconds).astype(np.int64)
    split_starts = np.flatnonzero(group_ids[1:] != group_ids[:-1]) + 1
    boundaries = [0] + split_starts.tolist() + [len(df)]

    return [
        df.iloc[start:end].reset_index(drop=True)
        for start, end in zip(boundaries[:-1], boundaries[1:])
        if start < end
    ]


class DataSplitter:
    """数据分割器"""

    def __init__(self, chip_rule: Optional[ChipRule] = None):
        self.chip_rule = chip_rule
        self.csv_handler = CSVHandler(chip_rule)
        self.last_collector = ResultCollector()

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
        result = self.split_file_result(
            input_file,
            output_dir,
            by_column=by_column,
            column_value=column_value,
            by_size=by_size,
            by_time=by_time,
            time_column=time_column,
            verbose=verbose,
        )
        if result.status != "OK":
            return []
        return [Path(p) for p in result.output.split(";") if p]

    def _error_result(self, input_file: Path, output_dir: Path, exc: Exception) -> FileResult:
        reason = classify_exception(exc, default=REASON_PROCESS_FAILED)
        if reason in {REASON_EMPTY_FILE, REASON_BAD_FORMAT, REASON_MISSING_COLUMN}:
            return FileResult(
                status=STATUS_SKIP,
                input=str(input_file),
                output=str(output_dir),
                reason=reason,
                detail=str(exc),
            )
        return FileResult(
            status=STATUS_FAIL,
            input=str(input_file),
            output=str(output_dir),
            reason=reason,
            detail=str(exc),
        )

    def split_file_result(
        self,
        input_file: Union[str, Path],
        output_dir: Union[str, Path],
        by_column: Optional[str] = None,
        column_value: Union[int, float] = 0,
        by_size: Optional[int] = None,
        by_time: Optional[float] = None,
        time_column: Optional[str] = None,
        verbose: bool = False,
    ) -> FileResult:
        """分割单个文件并返回结构化结果。"""
        input_file = Path(input_file)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            info, df = self.csv_handler.read(input_file)
        except Exception as e:
            return self._error_result(input_file, output_dir, e)

        if df.empty:
            return FileResult(
                status="SKIP",
                input=str(input_file),
                output=str(output_dir),
                reason=REASON_EMPTY_FILE,
                detail="CSV没有数据行",
            )

        try:
            if by_size:
                dfs = split_by_size(df, by_size)
            elif by_time and time_column:
                dfs = split_by_time(df, time_column, by_time)
            elif by_column:
                dfs = split_by_column_value(df, by_column, column_value)
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
                    pass

            if not output_files:
                return FileResult(
                    status=STATUS_SKIP,
                    input=str(input_file),
                    output=str(output_dir),
                    reason=REASON_EMPTY_FILE,
                    detail="分割后没有可写入的数据",
                )
        except Exception as e:
            return self._error_result(input_file, output_dir, e)

        return FileResult(
            status="OK",
            input=str(input_file),
            output=";".join(str(p) for p in output_files),
            rows=len(df),
        )

    def split_directory(
        self,
        input_dir: Union[str, Path],
        output_dir: Union[str, Path],
        by_column: Optional[str] = None,
        column_value: Union[int, float] = 0,
        by_size: Optional[int] = None,
        by_time: Optional[float] = None,
        time_column: Optional[str] = None,
        filter_name: Optional[str] = None,
        verbose: bool = False,
        show_progress: bool = False,
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
            filter_name: 文件名过滤（仅处理包含此字符串的文件）
            verbose: 详细输出
            show_progress: 是否显示进度条

        Returns:
            输出文件路径列表
        """
        input_dir = Path(input_dir)
        output_dir = Path(output_dir)

        files = list(input_dir.rglob("*.csv"))
        if filter_name:
            files = [f for f in files if filter_name in f.name]
        all_output_files = []
        self.last_collector = ResultCollector()

        for file in progress_track(files, "分割CSV...", enabled=show_progress):
            relative = file.relative_to(input_dir)
            file_output_dir = output_dir / relative.parent
            try:
                result = self.split_file_result(
                    file,
                    file_output_dir,
                    by_column,
                    column_value,
                    by_size,
                    by_time,
                    time_column,
                    verbose,
                )
            except Exception as exc:
                result = self._error_result(file, file_output_dir, exc)
            if result.status == "OK":
                all_output_files.extend(Path(p) for p in result.output.split(";") if p)
            self.last_collector.add(result)

        return all_output_files
