"""分类辅助函数模块"""

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def calculate_median(
    df: pd.DataFrame,
    column: Union[str, int],
    samples: int = 50,
) -> float:
    """
    计算指定列最后N个值的中值

    Args:
        df: DataFrame
        column: 列名或列索引
        samples: 采样数量

    Returns:
        中值
    """
    try:
        if isinstance(column, int):
            values = pd.to_numeric(df.iloc[-samples:, column], errors="coerce").values
        else:
            values = pd.to_numeric(df[column].iloc[-samples:], errors="coerce").values

        values = values[~np.isnan(values)]
        if len(values) == 0:
            return 0.0

        return float(np.median(values))
    except Exception as e:
        logger.warning("calculate_median 失败: %s", e)
        return 0.0


def calculate_mean(
    df: pd.DataFrame,
    column: Union[str, int],
) -> float:
    """
    计算指定列均值

    Args:
        df: DataFrame
        column: 列名或列索引

    Returns:
        均值
    """
    try:
        if isinstance(column, int):
            values = pd.to_numeric(df.iloc[:, column], errors="coerce")
        else:
            values = pd.to_numeric(df[column], errors="coerce")

        return float(values.mean())
    except Exception as e:
        logger.warning("calculate_mean 失败: %s", e)
        return 0.0


def calculate_std(
    df: pd.DataFrame,
    column: Union[str, int],
) -> float:
    """
    计算指定列标准差

    Args:
        df: DataFrame
        column: 列名或列索引

    Returns:
        标准差
    """
    try:
        if isinstance(column, int):
            values = pd.to_numeric(df.iloc[:, column], errors="coerce")
        else:
            values = pd.to_numeric(df[column], errors="coerce")

        return float(values.std())
    except Exception as e:
        logger.warning("calculate_std 失败: %s", e)
        return 0.0


def classify_by_range(
    value: float,
    ranges: Dict[str, List[float]],
) -> Optional[str]:
    """
    按范围分类

    Args:
        value: 数值
        ranges: 范围字典 {类别名: [最小值, 最大值]}

    Returns:
        类别名或None
    """
    for category, range_vals in ranges.items():
        if len(range_vals) >= 2:
            min_val, max_val = range_vals[0], range_vals[1]
            if min_val <= value <= max_val:
                return category
    return None


def extract_from_path(
    file_path: Union[str, Path],
    patterns: Dict[str, List[str]],
) -> str:
    """
    从文件路径提取信息

    Args:
        file_path: 文件路径
        patterns: 匹配模式字典 {类别名: [关键词列表]}

    Returns:
        类别名
    """
    path_str = str(file_path)

    sorted_patterns = sorted(
        patterns.items(),
        key=lambda x: max(len(k) for k in x[1]) if x[1] else 0,
        reverse=True,
    )

    for category, keywords in sorted_patterns:
        for keyword in keywords:
            if keyword in path_str:
                return category

    return "other"


def get_column_value(
    df: pd.DataFrame,
    column: Union[str, int],
    row: int = -1,
) -> Any:
    """
    获取指定列的值

    Args:
        df: DataFrame
        column: 列名或列索引
        row: 行索引（默认最后一行）

    Returns:
        列值
    """
    try:
        if isinstance(column, int):
            return df.iloc[row, column]
        return df[column].iloc[row]
    except Exception as e:
        logger.warning("get_column_value 失败: %s", e)
        return None


def calculate_percentile(
    df: pd.DataFrame,
    column: Union[str, int],
    percentile: float = 50,
) -> float:
    """
    计算指定列百分位数

    Args:
        df: DataFrame
        column: 列名或列索引
        percentile: 百分位数（0-100）

    Returns:
        百分位数值
    """
    try:
        if isinstance(column, int):
            values = pd.to_numeric(df.iloc[:, column], errors="coerce")
        else:
            values = pd.to_numeric(df[column], errors="coerce")

        return float(np.percentile(values.dropna(), percentile))
    except Exception as e:
        logger.warning("calculate_percentile 失败: %s", e)
        return 0.0


def count_values(
    df: pd.DataFrame,
    column: Union[str, int],
) -> Dict[Any, int]:
    """
    统计指定列的值计数

    Args:
        df: DataFrame
        column: 列名或列索引

    Returns:
        {值: 计数} 字典
    """
    try:
        if isinstance(column, int):
            values = df.iloc[:, column]
        else:
            values = df[column]

        return values.value_counts().to_dict()
    except Exception as e:
        logger.warning("count_values 失败: %s", e)
        return {}


CLASSIFY_FUNCTIONS = {
    "calculate_median": calculate_median,
    "calculate_mean": calculate_mean,
    "calculate_std": calculate_std,
    "classify_by_range": classify_by_range,
    "extract_from_path": extract_from_path,
    "get_column_value": get_column_value,
    "calculate_percentile": calculate_percentile,
    "count_values": count_values,
}


def get_function(name: str):
    """获取分类函数"""
    return CLASSIFY_FUNCTIONS.get(name)


def register_function(name: str, func: Callable) -> None:
    """注册自定义分类函数"""
    CLASSIFY_FUNCTIONS[name] = func
