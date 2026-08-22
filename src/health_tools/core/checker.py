"""数据检查核心逻辑"""

import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

from health_tools.models.rules import ChipRule
from health_tools.utils.columns import expand_columns

if TYPE_CHECKING:
    from health_tools.api.models import CheckAccuracyResult


@dataclass
class CheckResult:
    """单项检查结果"""

    name: str
    passed: bool
    summary: str
    details: List[str] = field(default_factory=list)
    status: str = ""
    abnormal_ratio: float = 0.0
    threshold_ratio: float = 0.0
    channel_metrics: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def __post_init__(self):
        if not self.status:
            self.status = "PASS" if self.passed else "FAIL"

    @property
    def failed(self) -> bool:
        return self.status == "FAIL"


@dataclass
class FileCheckReport:
    """单文件检查报告"""

    file_path: Path
    chip: str
    scene: str = "default"
    results: List[CheckResult] = field(default_factory=list)
    accuracy_result: Optional["CheckAccuracyResult"] = None
    accuracy_methods: Tuple[str, ...] = ()

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def total_status(self) -> str:
        return "PASS" if self.all_passed else "FAIL"


@dataclass
class AccChannelAnomaly:
    """单通道/组合的异常统计"""

    count: int = 0
    first_frame: int = -1
    max_duration: int = 0
    frames: List[int] = field(default_factory=list)


@dataclass
class AccAnomalyReport:
    """单文件ACC异常检测报告"""

    file_path: Path
    total_frames: int
    zero: AccChannelAnomaly = field(default_factory=AccChannelAnomaly)
    static_x: AccChannelAnomaly = field(default_factory=AccChannelAnomaly)
    static_y: AccChannelAnomaly = field(default_factory=AccChannelAnomaly)
    static_z: AccChannelAnomaly = field(default_factory=AccChannelAnomaly)
    static_xyz: AccChannelAnomaly = field(default_factory=AccChannelAnomaly)
    cyclic_x: AccChannelAnomaly = field(default_factory=AccChannelAnomaly)
    cyclic_y: AccChannelAnomaly = field(default_factory=AccChannelAnomaly)
    cyclic_z: AccChannelAnomaly = field(default_factory=AccChannelAnomaly)
    cyclic_xyz: AccChannelAnomaly = field(default_factory=AccChannelAnomaly)
    anomaly_indices: Set[int] = field(default_factory=set)

    @property
    def has_anomaly(self) -> bool:
        return self.anomaly_frame_count > 0

    @property
    def anomaly_frame_count(self) -> int:
        return len(self.anomaly_indices)

    @property
    def anomaly_ratio(self) -> float:
        if self.total_frames <= 0:
            return 0.0
        return self.anomaly_frame_count / self.total_frames * 100


class DataChecker:
    """PPG数据检查器"""

    ADC_FULL_SCALE = 2**23  # 8388608

    RANGE_MAP = {
        "gh3036": (0, 2**23),
        "gh3220": (2**23, 2**24),
        "gh3300": (2**23, 2**24),
    }

    CENTER_LOW = 0.3 * (2**23)  # 2516582
    CENTER_HIGH = 0.85 * (2**23)  # 7130317

    def __init__(self, chip_rule: ChipRule, tolerance: int = 50, static_min: int = 5):
        self.chip_rule = chip_rule
        self.tolerance = tolerance
        self.static_min = static_min
        self.chip_name = chip_rule.chip
        self._gain_tia_map = chip_rule.gain_tia_map or {}

    @staticmethod
    def _status_from_ratio(
        abnormal_count: int, total_count: int, threshold_ratio: float
    ) -> Tuple[str, float]:
        if abnormal_count <= 0:
            return "PASS", 0.0
        ratio = abnormal_count / total_count * 100 if total_count > 0 else 100.0
        if ratio <= threshold_ratio:
            return "WARNING", ratio
        return "FAIL", ratio

    @classmethod
    def _build_result(
        cls,
        name: str,
        abnormal_count: int,
        total_count: int,
        threshold_ratio: float,
        pass_summary: str,
        abnormal_summary: str,
        details: Optional[List[str]] = None,
        channel_metrics: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> CheckResult:
        status, ratio = cls._status_from_ratio(abnormal_count, total_count, threshold_ratio)
        return CheckResult(
            name=name,
            passed=status != "FAIL",
            summary=pass_summary if status == "PASS" else abnormal_summary,
            details=details or [],
            status=status,
            abnormal_ratio=ratio,
            threshold_ratio=threshold_ratio,
            channel_metrics=channel_metrics or {},
        )

    def run_all(self, df: pd.DataFrame) -> List[CheckResult]:
        """运行所有适用的检查"""
        results = []
        results.append(self.check_data_range(df))
        results.append(self.check_frame_completeness(df))
        results.append(self.check_data_centering(df))
        if self.chip_name.startswith("gh3036"):
            results.append(self.check_ipd_conversion(df))
        return results

    def _get_data_columns(self) -> List[str]:
        """获取原始数据列名：优先check_columns.data，其次从columns匹配"""
        context = getattr(self, "_check_context", None)
        if context is not None:
            return list(context.data_columns)
        explicit = self.chip_rule.check_columns.get("data")
        if explicit:
            return explicit
        columns = self.chip_rule.columns or []
        expanded = expand_columns(columns)
        rawdata_cols = [c for c in expanded if re.match(r"(?i)^(rawdata|ch)\d+$", c)]
        if rawdata_cols:
            return rawdata_cols
        if self.chip_name.startswith("gh3036"):
            return expand_columns(["Rawdata{0-31}"])
        elif self.chip_name.startswith("gh3220") or self.chip_name.startswith("gh3300"):
            return expand_columns(["CH{0-15}"]) + expand_columns(["CH{16-31}"])
        return []

    def _numeric_series(self, df: pd.DataFrame, column: str) -> pd.Series:
        """Return a per-file cached numeric series when check operation provides one."""
        context = getattr(self, "_check_context", None)
        if context is not None and context.frame is df:
            return context.numeric((column,))[column]
        return pd.to_numeric(df[column], errors="coerce")

    def _get_ipd_columns(self) -> List[str]:
        """获取Ipd列名：优先check_columns.ipd，其次从columns匹配"""
        context = getattr(self, "_check_context", None)
        if context is not None:
            return list(context.ipd_columns)
        explicit = self.chip_rule.check_columns.get("ipd")
        if explicit:
            return explicit
        columns = self.chip_rule.columns or []
        expanded = expand_columns(columns)
        ipd_cols = [c for c in expanded if re.match(r"(?i)^ipd[_\s]?pa?\d*$", c)]
        if ipd_cols:
            return ipd_cols
        return expand_columns(["Ipd{0-31}"])

    def _get_agc_columns(self) -> List[str]:
        """获取AGC_INFO列名：优先check_columns.agc，其次从columns匹配"""
        context = getattr(self, "_check_context", None)
        if context is not None:
            return list(context.agc_columns)
        explicit = self.chip_rule.check_columns.get("agc")
        if explicit:
            return explicit
        columns = self.chip_rule.columns or []
        expanded = expand_columns(columns)
        agc_cols = [c for c in expanded if re.match(r"(?i)^agc[_\s]?info\d*$", c)]
        if agc_cols:
            return agc_cols
        return expand_columns(["AGC_INFO_CH{0-31}"])

    @staticmethod
    def _is_all_zero_channel(series: pd.Series) -> bool:
        """判断已转换数值通道的有效值是否全为0。"""
        numeric = series.dropna()
        return not numeric.empty and bool((numeric == 0).all())

    def _filter_reserved_zero_channels(
        self, df: pd.DataFrame, columns: List[str]
    ) -> Tuple[List[str], List[str]]:
        """过滤整列有效值全0的PPG预留数据通道。"""
        active_cols: List[str] = []
        skipped_cols: List[str] = []
        for col in columns:
            if self._is_all_zero_channel(self._numeric_series(df, col)):
                skipped_cols.append(col)
            else:
                active_cols.append(col)
        return active_cols, skipped_cols

    @staticmethod
    def _append_skipped_summary(summary: str, skipped_count: int) -> str:
        """在检查摘要中补充跳过全0预留通道的信息。"""
        if skipped_count <= 0:
            return summary
        return f"{summary}；跳过 {skipped_count} 个全0预留通道"

    def _get_data_range(self) -> Tuple[float, float]:
        """获取原始数据范围：优先使用规则中的ADC偏置和满量程。"""
        chip_info = self.chip_rule.chip_info or {}
        if "adc_offset" in chip_info and "adc_full_scale" in chip_info:
            offset = float(chip_info["adc_offset"])
            full_scale = float(chip_info["adc_full_scale"])
            return offset, offset + full_scale

        return self.RANGE_MAP.get(self.chip_name, self.RANGE_MAP.get("gh3036", (0, 2**23)))

    def _adc_domain(self) -> Tuple[float, float]:
        info = self.chip_rule.chip_info or {}
        return float(info.get("adc_offset", 0)), float(
            info.get("adc_full_scale", self.ADC_FULL_SCALE)
        )

    def check_data_range(self, df: pd.DataFrame, threshold_ratio: float = 1.0) -> CheckResult:
        """检查原始数据是否在正常范围内"""
        all_data_cols = [c for c in self._get_data_columns() if c in df.columns]
        if not all_data_cols:
            return CheckResult("数据范围", False, "未找到数据列")
        data_cols, skipped_cols = self._filter_reserved_zero_channels(df, all_data_cols)
        if not data_cols:
            return CheckResult(
                "数据范围",
                True,
                f"全部 {len(skipped_cols)} 个全0预留通道已跳过，未检查有效数据列",
                status="PASS",
                threshold_ratio=threshold_ratio,
            )

        range_min, range_max = self._get_data_range()

        abnormal_cols: List[str] = []
        details: List[str] = []
        total_cells = 0
        total_abnormal = 0

        for col in data_cols:
            col_data = self._numeric_series(df, col).dropna()
            if col_data.empty:
                continue
            total_cells += len(col_data)
            out_of_range = ((col_data < range_min) | (col_data > range_max)).sum()
            if out_of_range > 0:
                total_abnormal += out_of_range
                pct = out_of_range / len(col_data) * 100
                abnormal_cols.append(col)
                details.append(f"{col}: {out_of_range}/{len(col_data)} 异常 ({pct:.1f}%)")

        pct = total_abnormal / total_cells * 100 if total_cells > 0 else 0
        col_names = ", ".join(abnormal_cols)
        return self._build_result(
            name="数据范围",
            abnormal_count=total_abnormal,
            total_count=total_cells,
            threshold_ratio=threshold_ratio,
            pass_summary=self._append_skipped_summary(
                f"全部 {len(data_cols)} 列数据在正常范围 [{range_min}, {range_max}]",
                len(skipped_cols),
            ),
            abnormal_summary=(
                f"{len(abnormal_cols)}/{len(data_cols)} 列超范围 [{col_names}], "
                f"共 {total_abnormal} 个异常值 ({pct:.1f}%)"
                + (f"；跳过 {len(skipped_cols)} 个全0预留通道" if skipped_cols else "")
            ),
            details=details,
        )

    def check_frame_completeness(
        self, df: pd.DataFrame, threshold_ratio: float = 1.0
    ) -> CheckResult:
        """检查帧号是否完整（丢包检测）"""
        frame_col = self._resolve_frame_column(df)
        if not frame_col:
            return CheckResult("帧完整性", False, "未找到帧号列")

        frame_ids = self._numeric_series(df, frame_col).dropna().astype(int)
        if frame_ids.empty:
            return CheckResult("帧完整性", False, "FRAME_ID 列无有效数据")

        actual_count = len(frame_ids)
        first_frame = int(frame_ids.iloc[0])
        start_offset = first_frame != 0

        if self.chip_name.startswith("gh3220"):
            lost = self._check_cyclic_frames(frame_ids, cycle=256)
        else:
            lost = self._check_incremental_frames(frame_ids)

        expected = actual_count + lost
        pct = lost / expected * 100
        result = self._build_result(
            name="帧完整性",
            abnormal_count=lost,
            total_count=expected,
            threshold_ratio=threshold_ratio,
            pass_summary=f"数据完整, 共 {actual_count} 帧, 无丢包",
            abnormal_summary=(
                f"丢包 {lost} 帧, 实际 {actual_count} 帧, 预期 {expected} 帧, " f"丢包率 {pct:.2f}%"
            ),
        )
        if start_offset:
            start_summary = f"首帧 {first_frame} 非起始帧 0"
            if lost == 0:
                result.status = "WARNING"
                result.passed = True
                result.summary = f"{start_summary}，后续帧连续"
            else:
                result.summary = f"{start_summary}；{result.summary}"
        return result

    def _check_cyclic_frames(self, frame_ids: pd.Series, cycle: int = 256) -> int:
        """检查循环帧号（GH3220: 0-255循环）"""
        values = frame_ids.to_numpy(dtype=np.int64, copy=False)
        if len(values) < 2:
            return 0
        expected = (values[:-1] + 1) % cycle
        gaps = (values[1:] - expected) % cycle
        return int(gaps[gaps > 0].sum())

    def _check_incremental_frames(self, frame_ids: pd.Series) -> int:
        """检查递增帧号（GH3036: 从0递增）"""
        diffs = frame_ids.diff().iloc[1:]
        gaps = diffs[diffs > 1]
        lost = int(gaps.sum() - len(gaps)) if len(gaps) > 0 else 0
        return lost

    def _get_center_raw_range(self) -> Tuple[float, float]:
        """获取数据居中检查展示用的原始码值范围。"""
        chip_info = self.chip_rule.chip_info or {}
        offset = float(chip_info.get("adc_offset", 0))
        return offset + self.CENTER_LOW, offset + self.CENTER_HIGH

    def check_data_centering(self, df: pd.DataFrame, threshold_ratio: float = 1.0) -> CheckResult:
        """检查数据去除基线后是否居中（0.3*2^23 ~ 0.85*2^23）"""
        all_data_cols = [c for c in self._get_data_columns() if c in df.columns]
        if not all_data_cols:
            return CheckResult("数据居中", False, "未找到数据列")
        data_cols, skipped_cols = self._filter_reserved_zero_channels(df, all_data_cols)
        if not data_cols:
            return CheckResult(
                "数据居中",
                True,
                f"全部 {len(skipped_cols)} 个全0预留通道已跳过，未检查有效数据列",
                status="PASS",
                threshold_ratio=threshold_ratio,
            )

        chip_info = self.chip_rule.chip_info or {}
        offset = float(chip_info.get("adc_offset", 0))
        center_min, center_max = self._get_center_raw_range()

        off_center_cols: List[str] = []
        details: List[str] = []
        total_cells = 0
        total_abnormal = 0
        channel_metrics: Dict[str, Dict[str, float]] = {}
        _, full_scale = self._adc_domain()
        center_low = 0.3 * full_scale
        center_high = 0.85 * full_scale

        for col in data_cols:
            col_data = self._numeric_series(df, col).dropna()
            if col_data.empty:
                continue
            total_cells += len(col_data)
            centered = col_data - offset
            out_low = (centered < center_low).sum()
            out_high = (centered > center_high).sum()
            out_total = out_low + out_high
            near_zero = centered <= 0.05 * full_scale
            near_full = centered >= 0.95 * full_scale
            channel_metrics[col] = {
                "abnormal_count": int(out_total),
                "total_count": int(len(col_data)),
                "abnormal_ratio": float(out_total / len(col_data) * 100),
                "low_count": int(out_low),
                "low_ratio": float(out_low / len(col_data) * 100),
                "high_count": int(out_high),
                "high_ratio": float(out_high / len(col_data) * 100),
                "near_zero_count": int(near_zero.sum()),
                "near_zero_ratio": float(near_zero.mean() * 100),
                "near_full_count": int(near_full.sum()),
                "near_full_ratio": float(near_full.mean() * 100),
            }
            if out_total > 0:
                total_abnormal += out_total
                pct = out_total / len(col_data) * 100
                off_center_cols.append(col)
                details.append(
                    f"{col}: {out_total}/{len(col_data)} 偏离 ({pct:.1f}%), "
                    f"偏低={out_low}, 偏高={out_high}"
                )

        col_names = ", ".join(off_center_cols)
        pct = total_abnormal / total_cells * 100 if total_cells > 0 else 0
        result = self._build_result(
            name="数据居中",
            abnormal_count=total_abnormal,
            total_count=total_cells,
            threshold_ratio=threshold_ratio,
            pass_summary=(
                self._append_skipped_summary(
                    f"全部 {len(data_cols)} 列数据居中正常 "
                    f"[{center_min:.0f}, {center_max:.0f}]",
                    len(skipped_cols),
                )
            ),
            abnormal_summary=(
                f"{len(off_center_cols)}/{len(data_cols)} 列偏离居中 [{col_names}], "
                f"共 {total_abnormal} 个异常值 ({pct:.1f}%)"
                + (f"；跳过 {len(skipped_cols)} 个全0预留通道" if skipped_cols else "")
            ),
            details=details,
        )
        result.channel_metrics = channel_metrics
        return result

    def check_agc_changes(self, df: pd.DataFrame) -> CheckResult:
        """统计 AGC_INFO 相邻有效样本的调光变化次数。"""
        metrics: Dict[str, Dict[str, float]] = {}
        for column in (name for name in self._get_agc_columns() if name in df.columns):
            values = self._numeric_series(df, column)
            valid_pairs = values.notna() & values.shift().notna()
            changes = valid_pairs & values.ne(values.shift())
            pair_count = int(valid_pairs.sum())
            change_count = int(changes.sum())
            metrics[column] = {
                "change_count": change_count,
                "total_count": pair_count,
                "change_ratio": float(change_count / pair_count * 100) if pair_count else 0.0,
            }
        return CheckResult(
            "AGC调光", True, "已统计 AGC 相邻变化", status="PASS", channel_metrics=metrics
        )

    def check_reference_data(
        self,
        df: pd.DataFrame,
        column: str,
        reference_type: str,
        sample_rate: float = 25.0,
        stale_seconds: float = 5.0,
        step_threshold: float = 8.0,
        warning_seconds: float = 10.0,
    ) -> CheckResult:
        """检查心率/血氧金标的范围、有效率、阶跃和静止异常。"""
        name_map = {"hr": "心率金标", "spo2": "血氧金标"}
        range_map = {"hr": (30.0, 240.0), "spo2": (70.0, 100.0)}
        name = name_map.get(reference_type, "金标")
        if reference_type not in range_map:
            return CheckResult(name, False, f"不支持的金标类型: {reference_type}")
        if (
            not np.isfinite(sample_rate)
            or sample_rate <= 0
            or not np.isfinite(stale_seconds)
            or stale_seconds <= 0
            or not np.isfinite(step_threshold)
            or step_threshold < 0
            or not np.isfinite(warning_seconds)
            or warning_seconds <= 0
        ):
            return CheckResult(name, False, "金标检测参数无效")
        if column not in df.columns:
            return CheckResult(name, False, f"未找到金标列: {column}")

        # Sampling can preserve source row labels (for example 0, 25, 50 ...).
        # All anomaly positions below are positional, so normalize both series
        # to a contiguous index before using ``loc``.
        values = self._numeric_series(df, column).reset_index(drop=True)
        total_count = int(len(values))
        finite = np.isfinite(values.to_numpy(dtype=float, na_value=np.nan))
        finite_values = values[finite]
        if total_count == 0 or finite_values.empty:
            return CheckResult(name, False, "金标列没有有效数值")

        low, high = range_map[reference_type]
        range_mask = (~finite) | (
            values.notna() & values.ne(0) & ((values < low) | (values > high))
        )
        range_count = int(range_mask.sum())
        zero_count = int((values == 0).fillna(False).sum())
        nonzero_ratio = (total_count - zero_count) / total_count * 100

        valid_pairs = values.notna() & values.shift().notna() & values.ne(0) & values.shift().ne(0)
        step_mask = valid_pairs & (values.diff().abs() > step_threshold)
        step_count = int(step_mask.sum())
        step_differences = values.diff().abs().where(step_mask)
        max_step_change = float(step_differences.max()) if step_count else 0.0

        valid_values = values.where(values.ne(0))
        groups = valid_values.ne(valid_values.shift()).cumsum()
        run_lengths = valid_values.notna().groupby(groups).sum()
        longest_run = int(run_lengths.max()) if not run_lengths.empty else 0
        stale_limit = sample_rate * stale_seconds
        longest_static_seconds = longest_run / sample_rate
        # 采样点间隔可能与配置采样率不一致（例如原始时间戳为 100 Hz、按 25 帧抽样），
        # 此时优先按同一行的 TimeStamp 真实跨度判断，避免把采样点数误标成秒数。
        timestamp = None
        if "time" in df.columns:
            timestamp = pd.to_numeric(df["time"], errors="coerce").reset_index(drop=True)
        if timestamp is not None:
            durations = []
            for _, run in valid_values.notna().groupby(groups):
                indices = run.index[run.to_numpy()]
                if len(indices) < 2:
                    continue
                start, end = indices[0], indices[-1]
                start_time, end_time = timestamp.loc[start], timestamp.loc[end]
                if pd.notna(start_time) and pd.notna(end_time) and end_time >= start_time:
                    durations.append(float(end_time - start_time) / 1000.0)
            if durations:
                longest_static_seconds = max(durations)
        stale = longest_static_seconds > stale_seconds

        def _time_at(index: int) -> str:
            if timestamp is None or index not in timestamp.index or pd.isna(timestamp.loc[index]):
                return str(index)
            value = timestamp.loc[index]
            if isinstance(value, (int, float, np.number)):
                numeric = float(value)
                if numeric.is_integer():
                    return str(int(numeric))
                return format(numeric, ".15g")
            return str(value)

        step_indices = np.flatnonzero(step_mask.to_numpy())
        max_step_time = (
            _time_at(int(step_indices[np.argmax(step_differences.iloc[step_indices])]))
            if step_count
            else ""
        )
        abnormal_times = []
        stale_positions = []
        if step_count:
            abnormal_times.extend(f"阶跃@{_time_at(int(index))}" for index in step_indices[:10])
        if stale:
            for _, run in valid_values.notna().groupby(groups):
                indices = run.index[run.to_numpy()]
                if len(indices) < 2:
                    continue
                start, end = indices[0], indices[-1]
                if timestamp is not None:
                    start_time, end_time = timestamp.loc[start], timestamp.loc[end]
                    duration = (
                        float(end_time - start_time) / 1000.0
                        if pd.notna(start_time) and pd.notna(end_time) and end_time >= start_time
                        else len(indices) / sample_rate
                    )
                else:
                    duration = len(indices) / sample_rate
                if duration > stale_seconds:
                    stale_positions.append(int(start))
                    if timestamp is not None:
                        abnormal_times.append(f"静止@{_time_at(int(start))}")
        if range_count:
            abnormal_times.extend(
                f"范围@{_time_at(int(index))}"
                for index in np.flatnonzero(range_mask.to_numpy())[:10]
            )

        metrics = {
            column: {
                "total_count": float(total_count),
                "range_abnormal_count": float(range_count),
                "nonzero_ratio": float(nonzero_ratio),
                "zero_count": float(zero_count),
                "step_count": float(step_count),
                "step_threshold": float(step_threshold),
                "max_step_change": max_step_change,
                "max_step_time": max_step_time,
                "abnormal_times": ";".join(abnormal_times[:20]),
                "longest_static_frames": int(longest_run),
                "static_frame_threshold": float(stale_limit),
                "longest_static_seconds": float(longest_static_seconds),
                "static_second_threshold": float(stale_seconds),
                "warning_seconds": float(warning_seconds),
            }
        }
        reasons = []
        if range_count:
            reasons.append(f"{range_count} 个值超出范围 {low:g}-{high:g}")
        if nonzero_ratio < 70.0:
            reasons.append(f"非零占比 {nonzero_ratio:.2f}% 低于 70%")
        if step_count:
            reasons.append(
                f"发现 {step_count} 次阶跃（阈值>{step_threshold:g}，最大变化 {max_step_change:g}，时间 {max_step_time}）"
            )
        if stale:
            reasons.append(f"最长静止 {longest_static_seconds:g} 秒，超过 {stale_seconds:g} 秒")
        summary = "；".join(reasons) if reasons else "金标数据正常"
        anomaly_positions = set()
        if range_count:
            anomaly_positions.update(int(index) for index in np.flatnonzero(range_mask.to_numpy()))
        if nonzero_ratio < 70.0:
            anomaly_positions.update(
                int(index) for index in np.flatnonzero((~values.notna() | values.eq(0)).to_numpy())
            )
        if step_count:
            anomaly_positions.update(int(index) for index in step_indices)
        anomaly_positions.update(stale_positions)

        timestamp_start = None
        if timestamp is not None:
            valid_timestamp = timestamp.dropna()
            if not valid_timestamp.empty:
                timestamp_start = float(valid_timestamp.iloc[0])

        def _in_warning_window(index: int) -> bool:
            if timestamp_start is not None and timestamp is not None:
                value = timestamp.loc[index]
                if pd.notna(value):
                    return float(value) - timestamp_start <= warning_seconds * 1000.0
            return index / sample_rate <= warning_seconds

        warning_only = (
            bool(reasons)
            and bool(anomaly_positions)
            and all(_in_warning_window(index) for index in anomaly_positions)
        )
        status = "WARNING" if warning_only else ("FAIL" if reasons else "PASS")
        return CheckResult(
            name,
            not reasons or warning_only,
            summary,
            status=status,
            channel_metrics=metrics,
        )

    def check_timestamp_interval(
        self,
        df: pd.DataFrame,
        timestamp_column: str,
        ratio_tolerance: float = 20.0,
        ms_tolerance: Optional[float] = None,
        threshold_ratio: float = 1.0,
        expected_base_ms: Optional[float] = None,
        _intervals_ms: Optional[pd.Series] = None,
        _parse_error: str = "",
    ) -> CheckResult:
        """检查相邻时间戳间隔是否稳定。"""
        if timestamp_column not in df.columns:
            return CheckResult("时间戳间隔", False, f"未找到时间戳列: {timestamp_column}")

        if _intervals_ms is None and not _parse_error:
            intervals_ms, error = self._parse_timestamp_intervals_ms(df[timestamp_column])
        else:
            intervals_ms, error = _intervals_ms, _parse_error
        if error:
            return CheckResult("时间戳间隔", False, error)

        if intervals_ms is None or len(intervals_ms) < 2:
            return CheckResult("时间戳间隔", False, "有效时间戳不足，至少需要3个点")

        if (intervals_ms < 0).any():
            return CheckResult("时间戳间隔", False, "时间戳倒退")

        baseline_ms = float(intervals_ms.median())
        if baseline_ms <= 0:
            return CheckResult("时间戳间隔", False, "基准间隔无效")

        base_deviation = None
        if expected_base_ms is not None:
            if not np.isfinite(expected_base_ms) or expected_base_ms <= 0:
                return CheckResult("时间戳间隔", False, "指定时间基准必须大于0且为有限数值")
            base_deviation = abs(baseline_ms - expected_base_ms) / expected_base_ms * 100
            if base_deviation > 20.0:
                return CheckResult(
                    "时间戳间隔",
                    False,
                    (
                        f"统计基准 {self._format_ms(baseline_ms)}，"
                        f"指定基准 {self._format_ms(expected_base_ms)}，"
                        f"偏差 {base_deviation:.1f}%，超过允许偏差 20%"
                    ),
                )

        diff_ms = (intervals_ms - baseline_ms).abs()
        ratio_limit = baseline_ms * ratio_tolerance / 100
        abnormal_mask = diff_ms > ratio_limit
        limits = [f"±{ratio_tolerance:g}%"]

        if ms_tolerance is not None:
            abnormal_mask = abnormal_mask | (diff_ms > ms_tolerance)
            limits.append(f"±{ms_tolerance:g}ms")

        base_info = ""
        if expected_base_ms is not None and base_deviation is not None:
            base_info = (
                f"，指定基准 {self._format_ms(expected_base_ms)}"
                f"，偏差 {base_deviation:.1f}%（允许≤20%）"
            )

        abnormal_count = int(abnormal_mask.sum())
        total_count = len(intervals_ms)
        ratio = abnormal_count / total_count * 100 if total_count > 0 else 0
        max_diff_idx = diff_ms.idxmax()
        max_interval_ms = float(intervals_ms.loc[max_diff_idx])
        first_frame = self._timestamp_interval_frame(df, max_diff_idx)
        max_cluster_low = max_interval_ms * 0.98
        max_cluster_high = max_interval_ms * 1.02
        max_cluster_count = int(
            ((intervals_ms >= max_cluster_low) & (intervals_ms <= max_cluster_high)).sum()
        )
        max_info = (
            f"最大 {self._format_ms(max_interval_ms)}@帧{first_frame}; "
            f"近最大±2% {max_cluster_count}个"
        )

        details = []
        if abnormal_count:
            details.append(f"{max_info}，范围 [{max_cluster_low:.3f}, {max_cluster_high:.3f}]ms")
            abnormal_items = intervals_ms[abnormal_mask].head(10)
            for idx, interval in abnormal_items.items():
                details.append(
                    f"第{idx}个间隔: {interval:.3f}ms, " f"偏差 {abs(interval - baseline_ms):.3f}ms"
                )

        return self._build_result(
            name="时间戳间隔",
            abnormal_count=abnormal_count,
            total_count=total_count,
            threshold_ratio=threshold_ratio,
            pass_summary=(
                f"稳定 {total_count}个间隔; "
                f"基准 {self._format_ms(baseline_ms)}{self._format_limits(limits)}{base_info}; {max_info}"
            ),
            abnormal_summary=(
                f"异常 {abnormal_count}/{total_count}({ratio:.1f}%); "
                f"基准 {self._format_ms(baseline_ms)}{self._format_limits(limits)}{base_info}; {max_info}"
            ),
            details=details,
        )

    @staticmethod
    def _format_ms(value: float) -> str:
        """格式化毫秒数，整数省略小数。"""
        if abs(value - round(value)) < 0.001:
            return f"{round(value):.0f}ms"
        return f"{value:.3f}ms"

    @staticmethod
    def _format_limits(limits: List[str]) -> str:
        """格式化容差短描述。"""
        if not limits:
            return ""
        return "".join(limits) if len(limits) == 1 else "(" + "/".join(limits) + ")"

    def _timestamp_interval_frame(self, df: pd.DataFrame, interval_index) -> int:
        """获取异常间隔首次出现的帧号，优先使用帧号列。"""
        frame_col = self._resolve_frame_column(df)
        try:
            position = df.index.get_loc(interval_index)
            if isinstance(position, slice):
                position = position.start
            elif not isinstance(position, int):
                position = int(np.asarray(position).nonzero()[0][0])
        except Exception:
            position = int(interval_index) if isinstance(interval_index, (int, np.integer)) else 0

        if frame_col:
            frame_values = pd.to_numeric(df[frame_col], errors="coerce")
            if 0 <= position < len(frame_values) and pd.notna(frame_values.iloc[position]):
                return int(frame_values.iloc[position])

        return int(interval_index) if isinstance(interval_index, (int, np.integer)) else position

    @staticmethod
    def _parse_timestamp_intervals_ms(series: pd.Series) -> Tuple[Optional[pd.Series], str]:
        """解析时间戳并返回相邻间隔（毫秒）。"""
        raw = series.dropna()
        if raw.empty:
            return None, "时间戳列无有效数据"

        numeric = pd.to_numeric(raw, errors="coerce")
        if numeric.notna().sum() >= max(3, int(len(raw) * 0.8)):
            values = numeric.dropna().astype(float)
            diffs = values.diff().dropna()
            if diffs.empty:
                return None, "有效时间戳不足，至少需要3个点"
            median_diff = float(diffs.abs().median())
            unit_scale = 1000.0 if 0 < median_diff < 1 else 1.0
            return diffs * unit_scale, ""

        text = raw.astype(str).str.strip()
        parsed = pd.to_datetime(text, format="%H:%M:%S.%f", errors="coerce")
        if parsed.notna().sum() < 3:
            parsed = pd.to_datetime(text, format="%H:%M:%S", errors="coerce")
        if parsed.notna().sum() < 3:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                parsed = pd.to_datetime(text, errors="coerce")
        if parsed.notna().sum() < 3:
            return None, "无法解析时间戳"

        parsed = parsed.dropna()
        intervals = parsed.diff().dropna().dt.total_seconds() * 1000
        return intervals, ""

    def check_ipd_conversion(self, df: pd.DataFrame, threshold_ratio: float = 1.0) -> CheckResult:
        """检查GH3036的Ipd_pA与Rawdata转换是否在误差范围内（±tolerance pA）"""
        ipd_cols = [c for c in self._get_ipd_columns() if c in df.columns]
        data_cols = [c for c in self._get_data_columns() if c in df.columns]
        agc_cols = [c for c in self._get_agc_columns() if c in df.columns]

        if not ipd_cols or not data_cols:
            return CheckResult("Ipd转换", False, "未找到 Ipd 或 Rawdata 列")

        chip_info = self.chip_rule.chip_info or {}
        full_scale = float(chip_info.get("adc_full_scale", self.ADC_FULL_SCALE))
        offset = float(chip_info.get("adc_offset", 0))
        vref = float(chip_info.get("adc_vref", 1.8))
        tia_ratio = float(chip_info.get("tia_ratio", 2))

        gain_map = self._gain_tia_map.get("map", {}) if self._gain_tia_map else {}

        mismatch_cols: List[str] = []
        details: List[str] = []
        check_count = min(len(ipd_cols), len(data_cols))
        skipped_count = 0
        active_count = 0
        total_points = 0
        total_exceed = 0

        for i in range(check_count):
            ipd_col = ipd_cols[i]
            raw_col = data_cols[i]
            if ipd_col not in df.columns or raw_col not in df.columns:
                continue

            ipd_data = self._numeric_series(df, ipd_col)
            raw_data = self._numeric_series(df, raw_col)
            if self._is_all_zero_channel(ipd_data) or self._is_all_zero_channel(raw_data):
                skipped_count += 1
                continue
            active_count += 1

            gain_k = self._extract_gain_k_series(df, agc_cols, i, gain_map)

            expected_ipd_pa = (
                (raw_data - offset) / full_scale * vref * 1e6 / (tia_ratio * gain_k) * 1000
            )

            diff = (ipd_data - expected_ipd_pa).abs()
            valid_mask = ipd_data.notna() & raw_data.notna()
            valid_diff = diff[valid_mask]

            if valid_diff.empty:
                continue

            total_points += len(valid_diff)
            exceed = (valid_diff > self.tolerance).sum()
            if exceed > 0:
                total_exceed += exceed
                pct = exceed / len(valid_diff) * 100
                max_diff = valid_diff.max()
                mismatch_cols.append(f"{ipd_col}<->{raw_col}")
                details.append(
                    f"{ipd_col}: {exceed}/{len(valid_diff)} 超差 ({pct:.1f}%), "
                    f"最大差值={max_diff:.1f} pA"
                )

        if active_count == 0 and skipped_count > 0:
            return CheckResult(
                "Ipd转换",
                True,
                f"全部 {skipped_count} 个全0预留通道已跳过，未检查有效通道",
                status="PASS",
                threshold_ratio=threshold_ratio,
            )

        col_names = ", ".join(mismatch_cols)
        pct = total_exceed / total_points * 100 if total_points > 0 else 0
        return self._build_result(
            name="Ipd转换",
            abnormal_count=total_exceed,
            total_count=total_points,
            threshold_ratio=threshold_ratio,
            pass_summary=self._append_skipped_summary(
                f"全部 {active_count} 通道 Ipd_pA 与 Rawdata 转换误差在 ±{self.tolerance} pA 内",
                skipped_count,
            ),
            abnormal_summary=(
                f"{len(mismatch_cols)}/{active_count} 通道超差 [{col_names}], "
                f"共 {total_exceed} 个超差点 ({pct:.1f}%)"
                + (f"；跳过 {skipped_count} 个全0预留通道" if skipped_count else "")
            ),
            details=details,
        )

    def build_ipd_detail(self, df: pd.DataFrame) -> pd.DataFrame:
        """构建Ipd超差详情DataFrame，仅包含任一通道超差的行"""
        ipd_cols = [c for c in self._get_ipd_columns() if c in df.columns]
        data_cols = [c for c in self._get_data_columns() if c in df.columns]
        agc_cols = [c for c in self._get_agc_columns() if c in df.columns]

        if not ipd_cols or not data_cols:
            return pd.DataFrame()

        chip_info = self.chip_rule.chip_info or {}
        full_scale = float(chip_info.get("adc_full_scale", self.ADC_FULL_SCALE))
        offset = float(chip_info.get("adc_offset", 0))
        vref = float(chip_info.get("adc_vref", 1.8))
        tia_ratio = float(chip_info.get("tia_ratio", 2))
        gain_map = self._gain_tia_map.get("map", {}) if self._gain_tia_map else {}

        frame_col = self._resolve_frame_column(df)
        check_count = min(len(ipd_cols), len(data_cols))

        result = pd.DataFrame(index=df.index)
        if frame_col:
            result["frame"] = df[frame_col]
        else:
            result["frame"] = range(len(df))

        exceed_any = pd.Series(False, index=df.index)

        for i in range(check_count):
            raw_col = data_cols[i]
            ipd_col = ipd_cols[i]
            agc_col = agc_cols[i] if i < len(agc_cols) else None

            raw_data = self._numeric_series(df, raw_col)
            ipd_data = self._numeric_series(df, ipd_col)
            gain_k = self._extract_gain_k_series(df, agc_cols, i, gain_map)

            expected = (raw_data - offset) / full_scale * vref * 1e6 / (tia_ratio * gain_k) * 1000
            diff = (ipd_data - expected).abs()
            exceed = diff > self.tolerance

            result[raw_col] = raw_data
            result[ipd_col] = ipd_data
            if agc_col and agc_col in df.columns:
                result[agc_col] = df[agc_col]
            result[f"expected_ipd{i}"] = expected.round(1)
            result[f"diff{i}"] = diff.round(1)
            result[f"exceed{i}"] = exceed.astype(int)

            exceed_any |= exceed.fillna(False)

        return result[exceed_any].reset_index(drop=True)

    def _extract_gain_k_series(
        self,
        df: pd.DataFrame,
        agc_cols: List[str],
        ch_index: int,
        gain_map: Dict,
    ) -> pd.Series:
        """从AGC_INFO逐行提取gain值并映射为kΩ，返回与df等长的Series"""
        default_gain = 100.0
        if ch_index >= len(agc_cols) or agc_cols[ch_index] not in df.columns:
            return pd.Series(default_gain, index=df.index)

        agc_data = self._numeric_series(df, agc_cols[ch_index])
        gain_codes = (agc_data.fillna(0).astype(int)) & 0x0F

        def _map_gain(code: int) -> float:
            return float(gain_map.get(code, gain_map.get(str(code), default_gain)))

        return gain_codes.map(_map_gain)

    # ──────────────────────────────────────────────────────────────────────
    # ACC 异常检测
    # ──────────────────────────────────────────────────────────────────────

    _ACC_AXIS_PATTERNS = [
        re.compile(r"(?i).*acc.*x.*"),
        re.compile(r"(?i).*acc.*y.*"),
        re.compile(r"(?i).*acc.*z.*"),
    ]
    _BARE_XYZ_PATTERNS = [
        re.compile(r"(?i)^x$"),
        re.compile(r"(?i)^y$"),
        re.compile(r"(?i)^z$"),
    ]
    _FRAME_PATTERNS = [
        re.compile(r"(?i)^frame[_\s]?id$"),
        re.compile(r"(?i)^frame[_\s]?cnt$"),
        re.compile(r"(?i)^frame$"),
        re.compile(r"(?i)^fid$"),
    ]

    def _resolve_acc_columns(self, df: pd.DataFrame) -> List[str]:
        """解析ACC列名：优先使用规则文件指定，否则自动检测"""
        context = getattr(self, "_check_context", None)
        if context is not None:
            return list(context.acc_columns)
        acc_map = self.chip_rule.acc_columns
        if acc_map:
            cols = [acc_map.get("x", ""), acc_map.get("y", ""), acc_map.get("z", "")]
            return [c for c in cols if c and c in df.columns]

        # 自动检测：先匹配含acc+xyz的列名，再匹配纯xyz
        found = []
        for patterns in (self._ACC_AXIS_PATTERNS, self._BARE_XYZ_PATTERNS):
            for pat in patterns:
                for col in df.columns:
                    if pat.match(col):
                        found.append(col)
                        break
            if len(found) == 3:
                return found
            found = []

        return found

    def _resolve_frame_column(self, df: pd.DataFrame) -> str:
        """解析帧号列名：优先使用规则文件指定，否则自动检测"""
        context = getattr(self, "_check_context", None)
        if context is not None:
            return context.frame_column
        specified = self.chip_rule.frame_column
        if specified and specified in df.columns:
            return specified

        for pat in self._FRAME_PATTERNS:
            for col in df.columns:
                if pat.match(col):
                    return col
        return ""

    def _get_frame_ids(self, df: pd.DataFrame) -> pd.Series:
        """获取帧号序列，无法识别帧号列时使用行索引"""
        frame_col = self._resolve_frame_column(df)
        if frame_col:
            return self._numeric_series(df, frame_col).fillna(0).astype(int)
        return pd.Series(range(len(df)), index=df.index)

    def _get_acc_display_frames(self, df: pd.DataFrame) -> pd.Series:
        """获取ACC异常报告展示用帧号；GH3220循环帧使用行号便于定位。"""
        if self.chip_name.startswith("gh3220"):
            return pd.Series(range(len(df)), index=df.index)
        return self._get_frame_ids(df)

    def check_acc_anomaly(
        self, df: pd.DataFrame, include_single_axis: bool = False
    ) -> AccAnomalyReport:
        """检测ACC数据异常（全零/静止/循环）"""
        acc_cols = self._resolve_acc_columns(df)
        frame_ids = self._get_acc_display_frames(df)
        report = AccAnomalyReport(file_path=Path(""), total_frames=len(df))

        if not acc_cols:
            return report

        context = getattr(self, "_check_context", None)
        if context is not None and context.frame is df:
            acc_df = context.numeric(tuple(acc_cols))
        else:
            acc_df = df[acc_cols].apply(pd.to_numeric, errors="coerce")

        self._check_acc_all_zero(acc_df, frame_ids, report)
        per_ch_static = self._check_acc_static(
            acc_df, frame_ids, report, include_single_axis=include_single_axis
        )
        self._check_acc_cyclic(
            acc_df, per_ch_static, frame_ids, report, include_single_axis=include_single_axis
        )

        return report

    def build_acc_result(
        self, report: AccAnomalyReport, threshold_ratio: float = 1.0
    ) -> CheckResult:
        """根据ACC异常帧占比构建三态检查结果"""
        details = []
        if report.has_anomaly:
            details.append(
                f"异常帧 {report.anomaly_frame_count}/{report.total_frames} "
                f"({report.anomaly_ratio:.1f}%)"
            )
        return self._build_result(
            name="ACC异常",
            abnormal_count=report.anomaly_frame_count,
            total_count=report.total_frames,
            threshold_ratio=threshold_ratio,
            pass_summary=f"共 {report.total_frames} 帧, 未检测到ACC异常",
            abnormal_summary=(
                f"检测到ACC异常帧 {report.anomaly_frame_count}/{report.total_frames} "
                f"({report.anomaly_ratio:.1f}%)"
            ),
            details=details,
            channel_metrics={
                "-": {
                    "abnormal_count": report.anomaly_frame_count,
                    "total_count": report.total_frames,
                    "abnormal_ratio": report.anomaly_ratio,
                }
            },
        )

    @staticmethod
    def _record_anomaly_indices(report: AccAnomalyReport, segments: List[Tuple[int, int]]) -> None:
        for start, end in segments:
            report.anomaly_indices.update(range(start, end + 1))

    def _check_acc_all_zero(
        self, acc_df: pd.DataFrame, frame_ids: pd.Series, report: AccAnomalyReport
    ) -> None:
        """检测XYZ同时为0的连续段"""
        all_zero = (acc_df == 0).all(axis=1)
        segments = self._find_consecutive_segments(all_zero)
        if segments:
            self._record_anomaly_indices(report, segments)
            report.zero = AccChannelAnomaly(
                count=len(segments),
                first_frame=int(frame_ids.iloc[segments[0][0]]),
                max_duration=max(end - start + 1 for start, end in segments),
                frames=[int(frame_ids.iloc[s[0]]) for s in segments],
            )

    def _check_acc_static(
        self,
        acc_df: pd.DataFrame,
        frame_ids: pd.Series,
        report: AccAnomalyReport,
        include_single_axis: bool = False,
    ) -> Dict[str, np.ndarray]:
        """检测连续不变段落，三通道都有→归XYZ，否则归单通道"""
        per_ch_static: Dict[str, np.ndarray] = {}
        per_ch_segments: Dict[int, List[Tuple[int, int]]] = {}

        for idx, col in enumerate(acc_df.columns):
            values = acc_df[col].to_numpy(copy=False)
            unchanged = np.zeros(len(values), dtype=bool)
            if len(values) > 1:
                unchanged[1:] = values[1:] == values[:-1]
            segments = self._find_consecutive_segments(unchanged, min_length=self.static_min)
            ch_mask = np.zeros(len(values), dtype=bool)
            if segments:
                for start, end in segments:
                    ch_mask[start : end + 1] = True
            per_ch_static[col] = ch_mask
            per_ch_segments[idx] = segments

        has_x = len(per_ch_segments.get(0, [])) > 0
        has_y = len(per_ch_segments.get(1, [])) > 0
        has_z = len(per_ch_segments.get(2, [])) > 0

        if has_x and has_y and has_z:
            # 三通道都有静止→找同时静止的帧段（三通道mask交集）
            cols = list(acc_df.columns)
            combined_mask = per_ch_static[cols[0]] & per_ch_static[cols[1]] & per_ch_static[cols[2]]
            xyz_segs = self._find_consecutive_segments(combined_mask, min_length=self.static_min)
            if xyz_segs:
                self._record_anomaly_indices(report, xyz_segs)
                report.static_xyz = AccChannelAnomaly(
                    count=len(xyz_segs),
                    first_frame=int(frame_ids.iloc[xyz_segs[0][0]]),
                    max_duration=max(end - start + 1 for start, end in xyz_segs),
                    frames=[int(frame_ids.iloc[s[0]]) for s in xyz_segs],
                )
        else:
            targets = [report.static_x, report.static_y, report.static_z]
            for idx, segs in per_ch_segments.items():
                if idx < 3 and segs:
                    if include_single_axis:
                        self._record_anomaly_indices(report, segs)
                    targets[idx].count = len(segs)
                    targets[idx].first_frame = int(frame_ids.iloc[segs[0][0]])
                    targets[idx].max_duration = max(end - start + 1 for start, end in segs)
                    targets[idx].frames = [int(frame_ids.iloc[s[0]]) for s in segs]

        return per_ch_static

    def _check_acc_cyclic(
        self,
        acc_df: pd.DataFrame,
        per_ch_static: Dict[str, np.ndarray],
        frame_ids: pd.Series,
        report: AccAnomalyReport,
        include_single_axis: bool = False,
    ) -> None:
        """检测固定序列重复，三通道都有→归XYZ，否则归单通道"""
        per_ch_segments: Dict[int, List[Tuple[int, int, int]]] = {}

        for idx, col in enumerate(acc_df.columns):
            values = acc_df[col].values.copy()
            ch_static = per_ch_static.get(col, np.zeros(len(acc_df), dtype=bool))
            mask = ~ch_static
            segments = self._find_cyclic_segments_with_period(values, mask)
            per_ch_segments[idx] = segments

        has_x = len(per_ch_segments.get(0, [])) > 0
        has_y = len(per_ch_segments.get(1, [])) > 0
        has_z = len(per_ch_segments.get(2, [])) > 0

        if has_x and has_y and has_z:
            xyz_segs = self._find_xyz_cyclic_segments(
                per_ch_segments[0], per_ch_segments[1], per_ch_segments[2]
            )
            if xyz_segs:
                report.cyclic_xyz = AccChannelAnomaly(
                    count=len(xyz_segs),
                    first_frame=int(frame_ids.iloc[xyz_segs[0][0]]),
                    max_duration=max(end - start + 1 for start, end in xyz_segs),
                    frames=[int(frame_ids.iloc[s[0]]) for s in xyz_segs],
                )
                self._record_anomaly_indices(report, xyz_segs)

        if not report.cyclic_xyz.count:
            targets = [report.cyclic_x, report.cyclic_y, report.cyclic_z]
            for idx, segs in per_ch_segments.items():
                if idx < 3 and segs:
                    plain_segs = [(start, end) for start, end, _period in segs]
                    if include_single_axis:
                        self._record_anomaly_indices(report, plain_segs)
                    targets[idx].count = len(plain_segs)
                    targets[idx].first_frame = int(frame_ids.iloc[plain_segs[0][0]])
                    targets[idx].max_duration = max(end - start + 1 for start, end in plain_segs)
                    targets[idx].frames = [int(frame_ids.iloc[s[0]]) for s in plain_segs]

    @staticmethod
    def _find_consecutive_segments(mask, min_length: int = 1) -> List[Tuple[int, int]]:
        """找到布尔掩码中连续True的段落，返回(start_idx, end_idx)列表"""
        bool_mask = np.asarray(mask, dtype=bool)
        if len(bool_mask) == 0 or not bool_mask.any():
            return []

        padded = np.concatenate(([False], bool_mask, [False]))
        edges = np.flatnonzero(padded[1:] != padded[:-1])
        starts = edges[0::2]
        ends = edges[1::2] - 1
        return [
            (int(start), int(end))
            for start, end in zip(starts, ends)
            if end - start + 1 >= min_length
        ]

    @staticmethod
    def _find_cyclic_segments(
        values: np.ndarray,
        valid_mask: np.ndarray,
        min_period: int = 2,
        max_period: int = 50,
        min_amplitude: int = 20,
    ) -> List[Tuple[int, int]]:
        """在一维数组中检测固定序列重复(≥2个完整周期)，只在valid_mask为True的区域检测"""
        return [
            (start, end)
            for start, end, _period in DataChecker._find_cyclic_segments_with_period(
                values, valid_mask, min_period, max_period, min_amplitude
            )
        ]

    @staticmethod
    def _find_cyclic_segments_with_period(
        values: np.ndarray,
        valid_mask: np.ndarray,
        min_period: int = 2,
        max_period: int = 50,
        min_amplitude: int = 20,
    ) -> List[Tuple[int, int, int]]:
        """检测固定序列重复，并保留周期用于三轴一致性判断。"""
        n = len(values)
        if n < min_period * 2:
            return []

        values = np.asarray(values)
        valid_mask = np.asarray(valid_mask, dtype=bool)
        candidates: List[Tuple[int, int, int]] = []

        max_candidate_period = min(max_period, n // 2)
        for period in range(min_period, max_candidate_period + 1):
            pair_equal = (
                (values[:-period] == values[period:]) & valid_mask[:-period] & valid_mask[period:]
            )
            for start, equal_end in DataChecker._find_consecutive_segments(
                pair_equal, min_length=period
            ):
                pattern = values[start : start + period]
                if not np.isfinite(pattern).all():
                    continue
                if pattern.max() - pattern.min() < min_amplitude:
                    continue
                candidates.append((start, equal_end + period, period))

        segments: List[Tuple[int, int, int]] = []
        last_end = -1
        for start, end, period in sorted(candidates, key=lambda item: (item[0], item[2])):
            if start <= last_end:
                continue
            segments.append((int(start), int(end), int(period)))
            last_end = end

        return segments

    @staticmethod
    def _find_xyz_cyclic_segments(
        x_segments: List[Tuple[int, int, int]],
        y_segments: List[Tuple[int, int, int]],
        z_segments: List[Tuple[int, int, int]],
    ) -> List[Tuple[int, int]]:
        """查找三轴周期一致且时间重叠的循环段。"""
        xyz_segments: List[Tuple[int, int]] = []
        for x_start, x_end, x_period in x_segments:
            for y_start, y_end, y_period in y_segments:
                if y_period != x_period:
                    continue
                overlap_start = max(x_start, y_start)
                overlap_end = min(x_end, y_end)
                if overlap_end - overlap_start + 1 < x_period * 2:
                    continue
                for z_start, z_end, z_period in z_segments:
                    if z_period != x_period:
                        continue
                    start = max(overlap_start, z_start)
                    end = min(overlap_end, z_end)
                    if end - start + 1 >= x_period * 2:
                        xyz_segments.append((int(start), int(end)))

        merged: List[Tuple[int, int]] = []
        for start, end in sorted(xyz_segments):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return merged
