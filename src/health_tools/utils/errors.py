"""命令行文件处理异常归类。"""

from __future__ import annotations

from typing import Optional


REASON_EMPTY_FILE = "文件为空"
REASON_BAD_FORMAT = "格式不对"
REASON_READ_FAILED = "读取失败"
REASON_MISSING_COLUMN = "列缺失"
REASON_RULE_MISMATCH = "规则不匹配"
REASON_NO_DATA = "无有效数据"
REASON_TOO_SMALL = "文件过小"
REASON_TOO_FEW_ROWS = "行数不足"
REASON_PROCESS_FAILED = "处理失败"
REASON_EXTERNAL_FAILED = "外部工具失败"
REASON_UNKNOWN = "未知异常"


def classify_exception(exc: BaseException, default: str = REASON_PROCESS_FAILED) -> str:
    """将常见异常归类为面向用户的中文原因。"""
    try:
        import pandas as pd
    except Exception:  # pragma: no cover - pandas 是项目依赖，这里仅做兜底
        pd = None  # type: ignore[assignment]

    if isinstance(exc, FileNotFoundError):
        return REASON_READ_FAILED
    if isinstance(exc, UnicodeDecodeError):
        return REASON_BAD_FORMAT
    if isinstance(exc, KeyError):
        return REASON_MISSING_COLUMN
    if pd is not None:
        if isinstance(exc, pd.errors.EmptyDataError):
            return REASON_EMPTY_FILE
        if isinstance(exc, pd.errors.ParserError):
            return REASON_BAD_FORMAT
    if isinstance(exc, ValueError):
        text = str(exc)
        if "No objects to concatenate" in text:
            return REASON_EMPTY_FILE
        if "Usecols do not match" in text:
            return REASON_MISSING_COLUMN
        return default
    return default or REASON_UNKNOWN


def normalize_reason(reason: Optional[str]) -> str:
    """将空原因归一化为未知异常。"""
    if not reason:
        return REASON_UNKNOWN
    return reason
