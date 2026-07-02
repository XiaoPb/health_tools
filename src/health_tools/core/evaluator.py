"""批量准确度评估模块"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from health_tools.models.rules import EvaluateRule
from health_tools.utils.errors import REASON_EMPTY_FILE, REASON_MISSING_COLUMN
from health_tools.utils.accuracy import calculate_accuracy
from health_tools.utils.csv_handler import CSVHandler
from health_tools.utils.progress import progress_track
from health_tools.utils.reporting import ResultCollector


class PolarAnomalyDetector:
    def __init__(
        self, diff_threshold: float = 30, stale_minutes: float = 2, sample_rate: float = 25
    ):
        self.diff_threshold = diff_threshold
        self.stale_minutes = stale_minutes
        self.sample_rate = sample_rate

    def detect(self, ref_series: pd.Series) -> pd.Series:
        values = pd.to_numeric(ref_series, errors="coerce")
        anomaly = pd.Series(False, index=values.index)

        diff = values.diff().abs()
        anomaly |= diff > self.diff_threshold

        stale_frames = int(self.stale_minutes * 60 * self.sample_rate)
        if stale_frames < 2:
            return anomaly

        changed = values.diff().ne(0)
        group_id = changed.cumsum()
        group_sizes = group_id.map(group_id.value_counts())
        anomaly |= (group_sizes >= stale_frames) & values.notna()

        return anomaly

    def summarize(self, anomaly: pd.Series) -> Dict[str, Any]:
        total = len(anomaly)
        anomaly_count = int(anomaly.sum())
        return {
            "anomaly_count": anomaly_count,
            "anomaly_ratio": round(anomaly_count / total * 100, 2) if total > 0 else 0,
            "total_rows": total,
        }


class FileClassifier:
    def __init__(
        self,
        by_directory: Optional[Dict[str, List[str]]] = None,
        by_filename: Optional[Dict[str, List[str]]] = None,
        default: str = "other",
    ):
        self.by_directory = by_directory or {}
        self.by_filename = by_filename or {}
        self.default = default

    def classify(self, file_path: Path) -> str:
        parent_name = file_path.parent.name.lower()
        for category, keywords in self.by_directory.items():
            for kw in keywords:
                if kw.lower() in parent_name:
                    return category

        filename = file_path.stem.lower()
        for category, keywords in self.by_filename.items():
            for kw in keywords:
                if kw.lower() in filename:
                    return category

        return self.default


class BatchEvaluator:
    def __init__(
        self,
        rule: EvaluateRule,
        chip_rule=None,
        ref_column_col: Optional[int] = None,
        pred_column_col: Optional[int] = None,
    ):
        self.rule = rule
        self.chip_rule = chip_rule
        self.ref_column_col = ref_column_col
        self.pred_column_col = pred_column_col
        self.csv_handler = CSVHandler(chip_rule)
        self.detector = PolarAnomalyDetector(
            diff_threshold=rule.diff_threshold,
            stale_minutes=rule.stale_minutes,
            sample_rate=rule.sample_rate,
        )
        self.classifier = FileClassifier(
            by_directory=rule.classify.get("by_directory", {}),
            by_filename=rule.classify.get("by_filename", {}),
            default=rule.default_category,
        )
        self.last_collector = ResultCollector()
        self._last_skip_reason = ""
        self._last_skip_detail = ""

    def _resolve_column(self, df: pd.DataFrame, col_type: str) -> Optional[str]:
        """解析列: 显式列索引 > 列名匹配 > chip_rule映射回退"""
        col_idx_override = self.ref_column_col if col_type == "ref" else self.pred_column_col
        if col_idx_override is not None:
            col_idx = col_idx_override - 1
            if 0 <= col_idx < len(df.columns):
                return df.columns[col_idx]
            return None

        col_name = self.rule.ref_column if col_type == "ref" else self.rule.pred_column

        if col_name in df.columns:
            return col_name

        if self.chip_rule:
            ref_map = {}
            if col_type == "ref":
                if self.rule.type == "hr":
                    ref_map = self.chip_rule.hr_ref_column
                elif self.rule.type == "spo2":
                    ref_map = self.chip_rule.spo_ref_column
            elif col_type == "pred":
                if self.rule.type == "hr":
                    ref_map = self.chip_rule.hr_ref_column
                elif self.rule.type == "spo2":
                    ref_map = self.chip_rule.spo_ref_column

            if ref_map and col_name in ref_map:
                col_idx = ref_map[col_name] - 1
                if 0 <= col_idx < len(df.columns):
                    return df.columns[col_idx]

            if ref_map:
                for col_idx in ref_map.values():
                    idx = col_idx - 1
                    if 0 <= idx < len(df.columns):
                        return df.columns[idx]
                return None

        return None

    def _calculate_first_output_time(self, pred_series: pd.Series) -> float:
        values = pd.to_numeric(pred_series, errors="coerce")
        valid = values[(values.notna()) & (values != 0)]
        if valid.empty:
            return -1.0
        first_idx = valid.index[0]
        pos = pred_series.index.get_loc(first_idx)
        return pos / self.rule.sample_rate

    def _evaluate_file(self, file_path: Path) -> Optional[Dict[str, Any]]:
        self._last_skip_reason = ""
        self._last_skip_detail = ""
        try:
            _, df = self.csv_handler.read(file_path)
        except Exception as e:
            raise e

        if df is None or df.empty:
            self._last_skip_reason = REASON_EMPTY_FILE
            self._last_skip_detail = "CSV没有数据行"
            return None

        ref_col = self._resolve_column(df, "ref")
        pred_col = self._resolve_column(df, "pred")

        if ref_col is None or pred_col is None:
            self._last_skip_reason = REASON_MISSING_COLUMN
            self._last_skip_detail = "未找到参考列或预测列"
            return None

        category = self.classifier.classify(file_path)
        anomaly_mask = self.detector.detect(df[ref_col])
        anomaly_info = self.detector.summarize(anomaly_mask)

        methods = self.rule.methods or ["mae", "rmse", "std"]
        thresholds = self.rule.thresholds or []

        all_metrics = calculate_accuracy(df, ref_col, pred_col, methods, thresholds)

        clean_df = df[~anomaly_mask]
        if len(clean_df) > 0:
            filtered_metrics = calculate_accuracy(clean_df, ref_col, pred_col, methods, thresholds)
        else:
            filtered_metrics = {m: 0.0 for m in methods}
            filtered_metrics["samples"] = 0

        result = {
            "file": file_path.name,
            "file_path": str(file_path),
            "category": category,
            **anomaly_info,
            "metrics_all": all_metrics,
            "metrics_filtered": filtered_metrics,
        }

        if self.rule.first_output_time:
            result["first_output_time_s"] = self._calculate_first_output_time(df[pred_col])

        return result

    def evaluate_directory(
        self,
        input_dir: Path,
        output_dir: Path,
        filter_name: Optional[str] = None,
        verbose: bool = False,
        show_progress: bool = False,
    ) -> Dict[str, Path]:
        input_dir = Path(input_dir)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        csv_files = sorted(input_dir.rglob("*.csv"))
        if filter_name:
            csv_files = [f for f in csv_files if filter_name in f.name]
        if not csv_files:
            return {}

        results: List[Dict[str, Any]] = []
        self.last_collector = ResultCollector()
        for f in progress_track(csv_files, "评估CSV...", enabled=show_progress):
            if verbose:
                pass
            try:
                r = self._evaluate_file(f)
            except Exception as e:
                self.last_collector.add_exception(f, e)
                continue
            if r:
                results.append(r)
                self.last_collector.add_ok(f, rows=int(r.get("total_rows", 0) or 0))
            else:
                self.last_collector.add_skip(
                    f,
                    reason=self._last_skip_reason,
                    detail=self._last_skip_detail,
                )

        if not results:
            return {}

        output_paths = {}
        output_paths["file_details"] = self._write_file_details(results, output_dir)
        output_paths["anomaly_list"] = self._write_anomaly_list(results, output_dir)
        output_paths["accuracy_summary"] = self._write_summary(
            results, "metrics_all", output_dir, "accuracy_summary.csv"
        )
        output_paths["accuracy_filtered"] = self._write_summary(
            results, "metrics_filtered", output_dir, "accuracy_filtered.csv"
        )

        return output_paths

    def _write_file_details(self, results: List[Dict], output_dir: Path) -> Path:
        rows = []
        for r in results:
            row = {
                "file": r["file"],
                "category": r["category"],
                "anomaly_count": r["anomaly_count"],
                "anomaly_ratio(%)": r["anomaly_ratio"],
                "total_rows": r["total_rows"],
            }
            if self.rule.first_output_time:
                row["first_output_time(s)"] = round(r.get("first_output_time_s", -1), 2)
            for k, v in r["metrics_all"].items():
                row[k] = v
            rows.append(row)

        path = output_dir / "file_details.csv"
        pd.DataFrame(rows).to_csv(path, index=False)
        return path

    def _write_anomaly_list(self, results: List[Dict], output_dir: Path) -> Path:
        rows = []
        for r in results:
            if r["anomaly_count"] > 0:
                rows.append(
                    {
                        "file": r["file"],
                        "category": r["category"],
                        "anomaly_count": r["anomaly_count"],
                        "anomaly_ratio(%)": r["anomaly_ratio"],
                        "total_rows": r["total_rows"],
                    }
                )

        path = output_dir / "anomaly_list.csv"
        pd.DataFrame(rows).to_csv(path, index=False)
        return path

    def _write_summary(
        self, results: List[Dict], metrics_key: str, output_dir: Path, filename: str
    ) -> Path:
        category_data: Dict[str, List[Dict]] = {}
        for r in results:
            cat = r["category"]
            if cat not in category_data:
                category_data[cat] = []
            category_data[cat].append(r[metrics_key])

        rows = []

        for cat, metrics_list in sorted(category_data.items()):
            agg = self._aggregate_metrics(metrics_list)
            agg["category"] = cat
            agg["files"] = len(metrics_list)
            rows.append(agg)

        total_metrics = [r[metrics_key] for r in results]
        if total_metrics:
            total_agg = self._aggregate_metrics(total_metrics)
            total_agg["category"] = "TOTAL"
            total_agg["files"] = len(results)
            if self.rule.first_output_time:
                fot_values = [
                    r.get("first_output_time_s", -1)
                    for r in results
                    if r.get("first_output_time_s", -1) >= 0
                ]
                if fot_values:
                    total_agg["avg_first_output_time(s)"] = round(np.mean(fot_values), 2)
            rows.insert(0, total_agg)

        path = output_dir / filename
        pd.DataFrame(rows).to_csv(path, index=False)
        return path

    def _aggregate_metrics(self, metrics_list: List[Dict]) -> Dict[str, Any]:
        if not metrics_list:
            return {}

        total_samples = sum(m.get("samples", 0) for m in metrics_list)
        if total_samples == 0:
            return {"samples": 0}

        result: Dict[str, Any] = {"samples": total_samples}
        keys = [k for k in metrics_list[0].keys() if k != "samples"]

        for key in keys:
            weighted_sum = sum(m.get(key, 0) * m.get("samples", 0) for m in metrics_list)
            result[key] = round(weighted_sum / total_samples, 2) if total_samples > 0 else 0

        return result
