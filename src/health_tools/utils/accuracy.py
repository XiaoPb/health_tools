"""准确度计算模块"""

from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table

console = Console()


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


def calculate_within_threshold(diff: np.ndarray, threshold: float) -> float:
    """计算误差在阈值内的占比"""
    if len(diff) == 0:
        return 0.0
    return float(np.mean(np.abs(diff) <= threshold) * 100)


def calculate_within_percent(
    ref: np.ndarray, pred: np.ndarray, percent: float
) -> float:
    """计算误差在百分比内的占比"""
    if len(ref) == 0:
        return 0.0
    threshold = np.abs(ref) * percent / 100
    return float(np.mean(np.abs(ref - pred) <= threshold) * 100)


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


def calculate_accuracy(
    df: pd.DataFrame,
    ref_column: Union[str, int],
    pred_column: Union[str, int],
    methods: Optional[List[str]] = None,
    thresholds: Optional[List[dict]] = None,
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
    if methods is None:
        methods = ["std", "rmse", "mae", "within_1", "within_2", "within_3"]

    if isinstance(ref_column, int):
        ref = pd.to_numeric(df.iloc[:, ref_column], errors="coerce").values
    else:
        ref = pd.to_numeric(df[ref_column], errors="coerce").values

    if isinstance(pred_column, int):
        pred = pd.to_numeric(df.iloc[:, pred_column], errors="coerce").values
    else:
        pred = pd.to_numeric(df[pred_column], errors="coerce").values

    mask = ~(np.isnan(ref) | np.isnan(pred))
    ref = ref[mask]
    pred = pred[mask]
    diff = ref - pred

    results = {}

    for method in methods:
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
                results[method] = calculate_within_threshold(diff, threshold)
            except (IndexError, ValueError):
                pass

    if thresholds:
        for th in thresholds:
            name = th.get("name", "")
            if "value" in th:
                results[name] = calculate_within_threshold(diff, th["value"])
            elif "percent" in th:
                results[name] = calculate_within_percent(ref, pred, th["percent"])

    results["samples"] = len(ref)

    return results


class AccuracyCalculator:
    """准确度计算器"""

    def __init__(
        self,
        ref_column: Union[str, int],
        pred_column: Union[str, int],
        methods: Optional[List[str]] = None,
        thresholds: Optional[List[dict]] = None,
    ):
        self.ref_column = ref_column
        self.pred_column = pred_column
        self.methods = methods or ["std", "rmse", "mae", "within_1", "within_2", "within_3"]
        self.thresholds = thresholds or []

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
        )

        if category not in self.category_results:
            self.category_results[category] = {
                "samples": 0,
                "files": 0,
            }
            for key in result.keys():
                if key != "samples":
                    self.category_results[category][key] = 0.0

        samples = result.get("samples", 0)
        self.category_results[category]["samples"] += samples
        self.category_results[category]["files"] += 1
        self.category_files[category] = self.category_files.get(category, 0) + 1

        for key, value in result.items():
            if key != "samples" and key in self.category_results[category]:
                self.category_results[category][key] += value * samples

        self.total_samples += samples

        if isinstance(self.ref_column, int):
            ref_vals = pd.to_numeric(df.iloc[:, self.ref_column], errors="coerce").dropna().values
        else:
            ref_vals = pd.to_numeric(df[self.ref_column], errors="coerce").dropna().values

        if isinstance(self.pred_column, int):
            pred_vals = pd.to_numeric(df.iloc[:, self.pred_column], errors="coerce").dropna().values
        else:
            pred_vals = pd.to_numeric(df[self.pred_column], errors="coerce").dropna().values

        min_len = min(len(ref_vals), len(pred_vals))
        self.total_ref.extend(ref_vals[:min_len].tolist())
        self.total_pred.extend(pred_vals[:min_len].tolist())

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
        )

    def print_report(self) -> None:
        """打印准确度报告"""
        self.finalize()
        total_results = self.get_total_results()

        console.print("\n[bold cyan]==================== 准确度报告 ====================[/bold cyan]\n")

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
