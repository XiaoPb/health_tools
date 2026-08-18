"""准确度计算模块"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd
from rich.console import Console

console = Console()

DEFAULT_ACCURACY_THRESHOLDS = (5.0, 10.0, 15.0)
DEFAULT_ACCURACY_METHODS = (
    "std",
    "rmse",
    "mae",
    "within_5",
    "within_10",
    "within_15",
)


@dataclass(frozen=True)
class PreparedAccuracyColumns:
    """统一裁剪后的准确度列。"""

    columns: Dict[str, np.ndarray]
    active_columns: Tuple[str, ...]
    start: int
    end: int


def normalize_accuracy_thresholds(
    thresholds: Optional[Sequence[float]],
) -> Optional[Tuple[float, ...]]:
    """校验并规范化准确度阈值，同时保留输入顺序。"""
    if thresholds is None:
        return None
    if not thresholds:
        raise ValueError("准确度阈值不能为空")

    normalized = []
    for threshold in thresholds:
        try:
            value = float(threshold)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"无效的准确度阈值: {threshold}") from exc
        if not np.isfinite(value) or value <= 0:
            raise ValueError(f"准确度阈值必须是有限正数: {threshold}")
        if value in normalized:
            raise ValueError(f"准确度阈值不能重复: {threshold}")
        normalized.append(value)
    return tuple(normalized)


def _format_accuracy_threshold(threshold: float) -> str:
    if threshold.is_integer():
        return str(int(threshold))
    return repr(threshold)


def _is_within_method(method: str) -> bool:
    if not method.startswith("within_"):
        return False
    try:
        return float(method.removeprefix("within_")) > 0
    except ValueError:
        return False


def resolve_accuracy_methods(
    methods: Optional[Sequence[str]], override: Optional[Sequence[float]]
) -> List[str]:
    """解析准确度方法，并按需替换固定数值阈值方法。"""
    resolved = list(methods) if methods else list(DEFAULT_ACCURACY_METHODS)
    normalized = normalize_accuracy_thresholds(override)
    if normalized is None:
        return resolved

    replacement = [f"within_{_format_accuracy_threshold(value)}" for value in normalized]
    indices = [index for index, method in enumerate(resolved) if _is_within_method(method)]
    if not indices:
        return [*resolved, *replacement]

    first_index = indices[0]
    before_first = sum(not _is_within_method(method) for method in resolved[:first_index])
    retained = [method for method in resolved if not _is_within_method(method)]
    return retained[:before_first] + replacement + retained[before_first:]


def prepare_accuracy_columns(
    columns: Mapping[str, Union[Sequence[float], np.ndarray]],
) -> PreparedAccuracyColumns:
    """按所有启用列的共同有效边界统一裁剪准确度数据。"""
    numeric_columns: Dict[str, np.ndarray] = {}
    lengths = set()
    for name, values in columns.items():
        array = np.asarray(pd.to_numeric(np.asarray(values), errors="coerce"), dtype=float)
        if array.ndim != 1:
            raise ValueError("准确度列必须是一维数据")
        numeric_columns[name] = array
        lengths.add(len(array))

    if len(lengths) > 1:
        raise ValueError("准确度列长度必须一致")

    active_columns = tuple(
        name
        for name, values in numeric_columns.items()
        if np.any(np.isfinite(values) & (values != 0))
    )
    if not active_columns:
        return PreparedAccuracyColumns(
            {name: values[:0] for name, values in numeric_columns.items()}, (), 0, 0
        )

    ready = np.logical_and.reduce(
        [
            np.isfinite(numeric_columns[name]) & (numeric_columns[name] != 0)
            for name in active_columns
        ]
    )
    ready_indices = np.flatnonzero(ready)
    if len(ready_indices) == 0:
        return PreparedAccuracyColumns(
            {name: values[:0] for name, values in numeric_columns.items()},
            active_columns,
            0,
            0,
        )

    start = int(ready_indices[0])
    end = int(ready_indices[-1]) + 1
    return PreparedAccuracyColumns(
        {name: values[start:end] for name, values in numeric_columns.items()},
        active_columns,
        start,
        end,
    )


def calculate_std(diff: np.ndarray) -> float:
    """计算误差标准差"""
    if len(diff) == 0:
        return 0.0
    return float(np.std(diff))


def calculate_rmse(diff: np.ndarray) -> float:
    """计算均方根误差"""
    if len(diff) == 0:
        return 0.0
    return float(np.sqrt(np.mean(diff**2)))


def calculate_mae(diff: np.ndarray) -> float:
    """计算平均绝对误差"""
    if len(diff) == 0:
        return 0.0
    return float(np.mean(np.abs(diff)))


def calculate_mape(ref: np.ndarray, pred: np.ndarray) -> float:
    """计算平均绝对百分比误差"""
    mask = ref != 0
    if not np.any(mask):
        return 0.0
    return float(np.mean(np.abs((ref[mask] - pred[mask]) / ref[mask])) * 100)


def calculate_within_threshold(
    diff: np.ndarray, threshold: float, inclusive: bool = False
) -> float:
    """计算误差在阈值内的占比"""
    if len(diff) == 0:
        return 0.0
    errors = np.abs(diff)
    matches = errors <= threshold if inclusive else errors < threshold
    return float(np.mean(matches) * 100)


def calculate_within_percent(
    ref: np.ndarray, pred: np.ndarray, percent: float, inclusive: bool = False
) -> float:
    """计算误差在百分比内的占比"""
    if len(ref) == 0:
        return 0.0
    threshold = np.abs(ref) * percent / 100
    errors = np.abs(ref - pred)
    matches = errors <= threshold if inclusive else errors < threshold
    return float(np.mean(matches) * 100)


def calculate_correlation(ref: np.ndarray, pred: np.ndarray) -> float:
    """计算相关系数"""
    if len(ref) < 2:
        return 0.0
    try:
        corr = np.corrcoef(ref, pred)
        if np.isnan(corr[0, 1]):
            return 0.0
        return float(corr[0, 1])
    except Exception:
        return 0.0


def calculate_r2(ref: np.ndarray, pred: np.ndarray) -> float:
    """计算R²决定系数"""
    if len(ref) == 0:
        return 0.0
    ss_res = np.sum((ref - pred) ** 2)
    ss_tot = np.sum((ref - np.mean(ref)) ** 2)
    if ss_tot == 0:
        return 0.0
    return float(1 - (ss_res / ss_tot))


def calculate_bias(diff: np.ndarray) -> float:
    """计算偏差（平均误差）"""
    if len(diff) == 0:
        return 0.0
    return float(np.mean(diff))


def _get_numeric_column(df: pd.DataFrame, column: Union[str, int]) -> np.ndarray:
    if isinstance(column, int):
        values = df.iloc[:, column]
    else:
        values = df[column]
    return pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)


def _prepare_accuracy_pair(
    df: pd.DataFrame,
    ref_column: Union[str, int],
    pred_column: Union[str, int],
    trim_zero_padding: bool,
) -> Tuple[np.ndarray, np.ndarray]:
    ref = _get_numeric_column(df, ref_column)
    pred = _get_numeric_column(df, pred_column)

    if trim_zero_padding:
        prepared = prepare_accuracy_columns({"ref": ref, "pred": pred})
        if len(prepared.active_columns) != 2 or prepared.start == prepared.end:
            return ref[:0], pred[:0]
        ref = prepared.columns["ref"]
        pred = prepared.columns["pred"]

    finite = np.isfinite(ref) & np.isfinite(pred)
    return ref[finite], pred[finite]


def calculate_accuracy(
    df: pd.DataFrame,
    ref_column: Union[str, int],
    pred_column: Union[str, int],
    methods: Optional[List[str]] = None,
    thresholds: Optional[List[dict]] = None,
    inclusive: bool = False,
    trim_zero_padding: bool = True,
) -> Dict[str, float]:
    """
    计算准确度指标

    Args:
        df: DataFrame
        ref_column: 参考列
        pred_column: 预测列
        methods: 计算方法列表
        thresholds: 自定义阈值列表

    Returns:
        准确度指标字典
    """
    resolved_methods = resolve_accuracy_methods(methods, None)
    ref, pred = _prepare_accuracy_pair(df, ref_column, pred_column, trim_zero_padding)
    if len(ref) == 0:
        return {"samples": 0}

    diff = ref - pred

    results = {}

    for method in resolved_methods:
        if method == "std":
            results["std"] = calculate_std(diff)
        elif method == "rmse":
            results["rmse"] = calculate_rmse(diff)
        elif method == "mae":
            results["mae"] = calculate_mae(diff)
        elif method == "mape":
            results["mape"] = calculate_mape(ref, pred)
        elif method == "bias":
            results["bias"] = calculate_bias(diff)
        elif method == "correlation":
            results["correlation"] = calculate_correlation(ref, pred)
        elif method == "r2":
            results["r2"] = calculate_r2(ref, pred)
        elif method.startswith("within_"):
            try:
                threshold = float(method.split("_")[1])
                results[method] = calculate_within_threshold(diff, threshold, inclusive)
            except (IndexError, ValueError):
                pass

    if thresholds:
        for th in thresholds:
            name = th.get("name", "")
            if "value" in th:
                results[name] = calculate_within_threshold(diff, th["value"], inclusive)
            elif "percent" in th:
                results[name] = calculate_within_percent(ref, pred, th["percent"], inclusive)

    results["samples"] = len(ref)

    # 所有数值保留两位小数
    for key in results:
        if key != "samples" and isinstance(results[key], float):
            results[key] = round(results[key], 2)

    return results


class AccuracyCalculator:
    """准确度计算器"""

    def __init__(
        self,
        ref_column: Union[str, int],
        pred_column: Union[str, int],
        methods: Optional[List[str]] = None,
        thresholds: Optional[List[dict]] = None,
        inclusive: bool = False,
        trim_zero_padding: bool = True,
    ):
        self.ref_column = ref_column
        self.pred_column = pred_column
        self.methods = resolve_accuracy_methods(methods, None)
        self.thresholds = thresholds or []
        self.inclusive = inclusive
        self.trim_zero_padding = trim_zero_padding

        self.category_results: Dict[str, Dict[str, float]] = {}
        self.category_files: Dict[str, int] = {}
        self.total_samples: int = 0
        self.total_ref: List[float] = []
        self.total_pred: List[float] = []

    def add_file_result(
        self,
        category: str,
        df: pd.DataFrame,
    ) -> Dict[str, float]:
        """添加文件结果"""
        result = calculate_accuracy(
            df,
            self.ref_column,
            self.pred_column,
            self.methods,
            self.thresholds,
            self.inclusive,
            self.trim_zero_padding,
        )

        samples = int(result.get("samples", 0))
        if samples == 0:
            return result

        if category not in self.category_results:
            self.category_results[category] = {
                "samples": 0,
                "files": 0,
            }
            for key in result.keys():
                if key != "samples":
                    self.category_results[category][key] = 0.0

        self.category_results[category]["samples"] += samples
        self.category_results[category]["files"] += 1
        self.category_files[category] = self.category_files.get(category, 0) + 1

        for key, value in result.items():
            if key != "samples" and key in self.category_results[category]:
                self.category_results[category][key] += value * samples

        self.total_samples += samples

        ref_vals, pred_vals = _prepare_accuracy_pair(
            df, self.ref_column, self.pred_column, self.trim_zero_padding
        )
        self.total_ref.extend(ref_vals.tolist())
        self.total_pred.extend(pred_vals.tolist())

        return result

    def finalize(self) -> None:
        """计算最终结果（加权平均）"""
        for category in self.category_results:
            samples = self.category_results[category]["samples"]
            if samples > 0:
                for key in self.category_results[category]:
                    if key not in ["samples", "files"]:
                        self.category_results[category][key] /= samples

    def get_total_results(self) -> Dict[str, float]:
        """获取整体结果"""
        if self.total_samples == 0:
            return {}

        ref_arr = np.array(self.total_ref)
        pred_arr = np.array(self.total_pred)

        min_len = min(len(ref_arr), len(pred_arr))
        if min_len == 0:
            return {}

        ref_arr = ref_arr[:min_len]
        pred_arr = pred_arr[:min_len]

        return calculate_accuracy(
            pd.DataFrame({"ref": ref_arr, "pred": pred_arr}),
            "ref",
            "pred",
            self.methods,
            self.thresholds,
            self.inclusive,
            False,
        )

    def print_report(self) -> None:
        """打印准确度报告"""
        self.finalize()
        total_results = self.get_total_results()

        console.print(
            "\n[bold cyan]==================== 准确度报告 ====================[/bold cyan]\n"
        )

        console.print(f"[bold]整体统计 (Total: {sum(self.category_files.values())} files)[/bold]")
        console.print("-" * 50)

        if total_results:
            for key, value in total_results.items():
                if key == "samples":
                    console.print(f"样本数:    {int(value)}")
                elif key.startswith("within_"):
                    console.print(f"±{key.split('_')[1]}占比:    {value:.1f}%")
                elif key in ["correlation", "r2"]:
                    console.print(f"{key}:  {value:.4f}")
                else:
                    console.print(f"{key.upper()}:       {value:.2f}")

        console.print("\n[bold]分类统计[/bold]")
        console.print("-" * 50)

        for category, results in sorted(self.category_results.items()):
            files = results.get("files", 0)
            console.print(f"\n[cyan]分类: {category} ({files} files)[/cyan]")

            for key, value in results.items():
                if key in ["samples", "files"]:
                    continue
                elif key.startswith("within_"):
                    console.print(f"  ±{key.split('_')[1]}占比:    {value:.1f}%")
                elif key in ["correlation", "r2"]:
                    console.print(f"  {key}:  {value:.4f}")
                else:
                    console.print(f"  {key.upper()}:       {value:.2f}")

    def save_report(self, output_path: Union[str, Path]) -> None:
        """保存报告到CSV文件"""
        self.finalize()
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        rows = []

        total_results = self.get_total_results()
        if total_results:
            row = {"category": "total", "files": sum(self.category_files.values())}
            row.update(total_results)
            rows.append(row)

        for category, results in sorted(self.category_results.items()):
            row = {
                "category": category,
                "files": results.get("files", 0),
            }
            for key, value in results.items():
                if key not in ["files"]:
                    row[key] = value
            rows.append(row)

        df = pd.DataFrame(rows)
        df.to_csv(output_path, index=False)
        console.print(f"\n[green]报告已保存: {output_path}[/green]")


def format_metric_name(metric: str) -> str:
    """将指标名转换为显示格式（如 within_5 → ±5BPM, mae → MAE）"""
    if metric.startswith("within_"):
        threshold = metric.split("_")[1]
        return f"±{threshold}BPM"
    name_map = {
        "mae": "MAE",
        "rmse": "RMSE",
        "std": "STD",
        "correlation": "CORR",
        "bias": "BIAS",
        "mape": "MAPE",
        "r2": "R²",
    }
    return name_map.get(metric, metric.upper())


ACCURACY_FUNCTIONS = {
    "std": calculate_std,
    "rmse": calculate_rmse,
    "mae": calculate_mae,
    "mape": calculate_mape,
    "within": calculate_within_threshold,
    "correlation": calculate_correlation,
    "r2": calculate_r2,
    "bias": calculate_bias,
}
