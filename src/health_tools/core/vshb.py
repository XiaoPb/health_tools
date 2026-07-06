"""_result.vshb 文件读取工具。"""

from pathlib import Path
from typing import Dict

import pandas as pd


VSHB_COLUMNS = ["time", "offline", "ref", "online"]
VSHB_HEADER_ALIASES = {
    "time": "second",
    "offline": "algo_hr",
    "ref": "polar",
    "online": "fw_hr",
}
VSHB_POSITIONAL_COLUMNS = {
    "time": 0,
    "offline": 1,
    "ref": 2,
}


def _empty_result() -> pd.DataFrame:
    return pd.DataFrame(columns=VSHB_COLUMNS)


def _normalize_column(name: object) -> str:
    return str(name).strip().lstrip("\ufeff").lower()


def _column_exists(df: pd.DataFrame, index: int) -> bool:
    return -df.shape[1] <= index < df.shape[1]


def _build_numeric_frame(columns: Dict[str, pd.Series]) -> pd.DataFrame:
    return pd.DataFrame(
        {name: pd.to_numeric(series, errors="coerce") for name, series in columns.items()}
    )


def _read_by_header(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=False)
    column_map = {_normalize_column(column): column for column in df.columns}
    if not all(alias in column_map for alias in VSHB_HEADER_ALIASES.values()):
        return _empty_result()

    return _build_numeric_frame(
        {target: df[column_map[source]] for target, source in VSHB_HEADER_ALIASES.items()}
    )


def _read_by_position(path: Path, online_col: int) -> pd.DataFrame:
    df = pd.read_csv(path, header=None)
    required = list(VSHB_POSITIONAL_COLUMNS.values()) + [online_col]
    if not all(_column_exists(df, index) for index in required):
        return _empty_result()

    return _build_numeric_frame(
        {
            "time": df.iloc[:, VSHB_POSITIONAL_COLUMNS["time"]],
            "offline": df.iloc[:, VSHB_POSITIONAL_COLUMNS["offline"]],
            "ref": df.iloc[:, VSHB_POSITIONAL_COLUMNS["ref"]],
            "online": df.iloc[:, online_col],
        }
    )


def read_vshb_result(
    path: Path,
    positional_online_col: int,
    filter_ref: bool = False,
) -> pd.DataFrame:
    """读取vshb结果，优先按表头列名读取，失败时回退到旧列号。"""
    try:
        result = _read_by_header(path)
    except Exception:
        result = _empty_result()

    if result.empty:
        try:
            result = _read_by_position(path, positional_online_col)
        except Exception:
            result = _empty_result()

    if filter_ref and not result.empty:
        result = result[result["ref"] > 0].reset_index(drop=True)
    return result
