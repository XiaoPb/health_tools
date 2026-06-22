"""数据检查核心逻辑"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from health_tools.models.rules import ChipRule
from health_tools.utils.columns import expand_columns


@dataclass
class CheckResult:
    """单项检查结果"""

    name: str
    passed: bool
    summary: str
    details: List[str] = field(default_factory=list)


@dataclass
class FileCheckReport:
    """单文件检查报告"""

    file_path: Path
    chip: str
    results: List[CheckResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)


@dataclass
class AccAnomalyReport:
    """单文件ACC异常检测报告"""

    file_path: Path
    total_frames: int
    zero_count: int = 0
    zero_channels: str = "-"
    zero_first_frame: int = -1
    zero_max_duration: int = 0
    static_count: int = 0
    static_channels: str = "-"
    static_first_frame: int = -1
    static_max_duration: int = 0
    cyclic_count: int = 0
    cyclic_channels: str = "-"
    cyclic_first_frame: int = -1
    cyclic_max_duration: int = 0

    @property
    def has_anomaly(self) -> bool:
        return self.zero_count > 0 or self.static_count > 0 or self.cyclic_count > 0


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

    def __init__(self, chip_rule: ChipRule, tolerance: int = 50):
        self.chip_rule = chip_rule
        self.tolerance = tolerance
        self.chip_name = chip_rule.chip
        self._gain_tia_map = chip_rule.gain_tia_map or {}

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
        """获取原始数据列名"""
        if self.chip_name.startswith("gh3036"):
            return expand_columns(["Rawdata{0-31}"])
        elif self.chip_name.startswith("gh3220"):
            cols = expand_columns(["CH{0-15}"])
            cols += expand_columns(["CH{16-31}"])
            return cols
        elif self.chip_name.startswith("gh3300"):
            return expand_columns(["CH{0-15}"]) + expand_columns(["CH{16-31}"])
        return []

    def _get_ipd_columns(self) -> List[str]:
        """获取Ipd列名（GH3036）"""
        return expand_columns(["Ipd{0-31}"])

    def _get_agc_columns(self) -> List[str]:
        """获取AGC_INFO列名"""
        return expand_columns(["AGC_INFO_CH{0-31}"])

    def check_data_range(self, df: pd.DataFrame) -> CheckResult:
        """检查原始数据是否在正常范围内"""
        data_cols = [c for c in self._get_data_columns() if c in df.columns]
        if not data_cols:
            return CheckResult("数据范围", False, "未找到数据列")

        range_min, range_max = self.RANGE_MAP.get(
            self.chip_name, self.RANGE_MAP.get("gh3036", (0, 2**23))
        )

        abnormal_cols: List[str] = []
        details: List[str] = []
        total_cells = 0
        total_abnormal = 0

        for col in data_cols:
            col_data = pd.to_numeric(df[col], errors="coerce").dropna()
            if col_data.empty:
                continue
            total_cells += len(col_data)
            out_of_range = ((col_data < range_min) | (col_data > range_max)).sum()
            if out_of_range > 0:
                total_abnormal += out_of_range
                pct = out_of_range / len(col_data) * 100
                abnormal_cols.append(col)
                details.append(f"{col}: {out_of_range}/{len(col_data)} 异常 ({pct:.1f}%)")

        if not abnormal_cols:
            return CheckResult(
                "数据范围",
                True,
                f"全部 {len(data_cols)} 列数据在正常范围 [{range_min}, {range_max}]",
            )

        pct = total_abnormal / total_cells * 100 if total_cells > 0 else 0
        return CheckResult(
            "数据范围",
            False,
            f"{len(abnormal_cols)}/{len(data_cols)} 列存在超范围数据, "
            f"共 {total_abnormal} 个异常值 ({pct:.1f}%)",
            details,
        )

    def check_frame_completeness(self, df: pd.DataFrame) -> CheckResult:
        """检查FRAME_ID是否完整（丢包检测）"""
        if "FRAME_ID" not in df.columns:
            return CheckResult("帧完整性", False, "未找到 FRAME_ID 列")

        frame_ids = pd.to_numeric(df["FRAME_ID"], errors="coerce").dropna().astype(int)
        if frame_ids.empty:
            return CheckResult("帧完整性", False, "FRAME_ID 列无有效数据")

        actual_count = len(frame_ids)

        if self.chip_name.startswith("gh3220"):
            lost = self._check_cyclic_frames(frame_ids, cycle=256)
        else:
            lost = self._check_incremental_frames(frame_ids)

        if lost == 0:
            return CheckResult(
                "帧完整性",
                True,
                f"数据完整, 共 {actual_count} 帧, 无丢包",
            )

        expected = actual_count + lost
        pct = lost / expected * 100
        return CheckResult(
            "帧完整性",
            False,
            f"丢包 {lost} 帧, 实际 {actual_count} 帧, " f"预期 {expected} 帧, 丢包率 {pct:.2f}%",
        )

    def _check_cyclic_frames(self, frame_ids: pd.Series, cycle: int = 256) -> int:
        """检查循环帧号（GH3220: 0-255循环）"""
        lost = 0
        prev = int(frame_ids.iloc[0])
        for i in range(1, len(frame_ids)):
            curr = int(frame_ids.iloc[i])
            expected_next = (prev + 1) % cycle
            if curr != expected_next:
                if curr > expected_next:
                    gap = curr - expected_next
                else:
                    gap = (cycle - expected_next) + curr
                lost += gap
            prev = curr
        return lost

    def _check_incremental_frames(self, frame_ids: pd.Series) -> int:
        """检查递增帧号（GH3036: 从0递增）"""
        diffs = frame_ids.diff().iloc[1:]
        gaps = diffs[diffs > 1]
        lost = int(gaps.sum() - len(gaps)) if len(gaps) > 0 else 0
        return lost

    def check_data_centering(self, df: pd.DataFrame) -> CheckResult:
        """检查数据去除基线后是否居中（0.3*2^23 ~ 0.85*2^23）"""
        data_cols = [c for c in self._get_data_columns() if c in df.columns]
        if not data_cols:
            return CheckResult("数据居中", False, "未找到数据列")

        chip_info = self.chip_rule.chip_info or {}
        offset = float(chip_info.get("adc_offset", 0))

        off_center_cols: List[str] = []
        details: List[str] = []

        for col in data_cols:
            col_data = pd.to_numeric(df[col], errors="coerce").dropna()
            if col_data.empty:
                continue
            centered = col_data - offset
            out_low = (centered < self.CENTER_LOW).sum()
            out_high = (centered > self.CENTER_HIGH).sum()
            out_total = out_low + out_high
            if out_total > 0:
                pct = out_total / len(col_data) * 100
                off_center_cols.append(col)
                details.append(
                    f"{col}: {out_total}/{len(col_data)} 偏离 ({pct:.1f}%), "
                    f"偏低={out_low}, 偏高={out_high}"
                )

        if not off_center_cols:
            return CheckResult(
                "数据居中",
                True,
                f"全部 {len(data_cols)} 列数据居中正常 "
                f"[{self.CENTER_LOW:.0f}, {self.CENTER_HIGH:.0f}]",
            )

        return CheckResult(
            "数据居中",
            False,
            f"{len(off_center_cols)}/{len(data_cols)} 列数据偏离居中范围",
            details,
        )

    def check_ipd_conversion(self, df: pd.DataFrame) -> CheckResult:
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

        for i in range(check_count):
            ipd_col = ipd_cols[i]
            raw_col = data_cols[i]
            if ipd_col not in df.columns or raw_col not in df.columns:
                continue

            ipd_data = pd.to_numeric(df[ipd_col], errors="coerce")
            raw_data = pd.to_numeric(df[raw_col], errors="coerce")

            gain_k = self._extract_gain_k(df, agc_cols, i, gain_map)

            expected_ipd_pa = (
                (raw_data - offset) / full_scale * vref * 1e6 / (tia_ratio * gain_k) * 1000
            )

            diff = (ipd_data - expected_ipd_pa).abs()
            valid_mask = ipd_data.notna() & raw_data.notna()
            valid_diff = diff[valid_mask]

            if valid_diff.empty:
                continue

            exceed = (valid_diff > self.tolerance).sum()
            if exceed > 0:
                pct = exceed / len(valid_diff) * 100
                max_diff = valid_diff.max()
                mismatch_cols.append(f"{ipd_col}<->{raw_col}")
                details.append(
                    f"{ipd_col}: {exceed}/{len(valid_diff)} 超差 ({pct:.1f}%), "
                    f"最大差值={max_diff:.1f} pA"
                )

        if not mismatch_cols:
            return CheckResult(
                "Ipd转换",
                True,
                f"全部 {check_count} 通道 Ipd_pA 与 Rawdata 转换误差在 ±{self.tolerance} pA 内",
            )

        return CheckResult(
            "Ipd转换",
            False,
            f"{len(mismatch_cols)}/{check_count} 通道转换误差超过 ±{self.tolerance} pA",
            details,
        )

    def _extract_gain_k(
        self,
        df: pd.DataFrame,
        agc_cols: List[str],
        ch_index: int,
        gain_map: Dict,
    ) -> float:
        """从AGC_INFO提取gain值并映射为kΩ"""
        if ch_index < len(agc_cols) and agc_cols[ch_index] in df.columns:
            agc_data = pd.to_numeric(df[agc_cols[ch_index]], errors="coerce")
            valid_agc = agc_data.dropna()
            if not valid_agc.empty:
                agc_val = int(valid_agc.iloc[0])
                gain_code = agc_val & 0x0F
                gain_k = gain_map.get(gain_code, gain_map.get(str(gain_code), 100))
                return float(gain_k)
        return 100.0

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
        re.compile(r"(?i)^frame$"),
        re.compile(r"(?i)^fid$"),
    ]

    def _resolve_acc_columns(self, df: pd.DataFrame) -> List[str]:
        """解析ACC列名：优先使用规则文件指定，否则自动检测"""
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
            return pd.to_numeric(df[frame_col], errors="coerce").fillna(0).astype(int)
        return pd.Series(range(len(df)), index=df.index)

    def check_acc_anomaly(self, df: pd.DataFrame) -> AccAnomalyReport:
        """检测ACC数据异常（全零/静止/循环）"""
        acc_cols = self._resolve_acc_columns(df)
        frame_ids = self._get_frame_ids(df)
        report = AccAnomalyReport(file_path=Path(""), total_frames=len(df))

        if not acc_cols:
            return report

        acc_df = df[acc_cols].apply(pd.to_numeric, errors="coerce")

        self._check_acc_all_zero(acc_df, frame_ids, report)
        static_mask = self._check_acc_static(acc_df, frame_ids, report)
        self._check_acc_cyclic(acc_df, static_mask, frame_ids, report)

        return report

    def _check_acc_all_zero(
        self, acc_df: pd.DataFrame, frame_ids: pd.Series, report: AccAnomalyReport
    ) -> None:
        """检测XYZ同时为0的连续段"""
        all_zero = (acc_df == 0).all(axis=1)
        segments = self._find_consecutive_segments(all_zero)
        if segments:
            report.zero_count = len(segments)
            report.zero_channels = "XYZ"
            report.zero_first_frame = int(frame_ids.iloc[segments[0][0]])
            report.zero_max_duration = max(end - start + 1 for start, end in segments)

    def _check_acc_static(
        self, acc_df: pd.DataFrame, frame_ids: pd.Series, report: AccAnomalyReport
    ) -> pd.Series:
        """检测连续不变超过3个点的段落，返回静止掩码用于排除循环检测"""
        static_mask = pd.Series(False, index=acc_df.index)
        channel_has_static: List[str] = []
        all_segments: List[Tuple[int, int]] = []
        axis_labels = ["X", "Y", "Z"]

        for idx, col in enumerate(acc_df.columns):
            series = acc_df[col]
            unchanged = series.diff().eq(0)
            unchanged.iloc[0] = False
            segments = self._find_consecutive_segments(unchanged, min_length=3)
            if segments:
                ch_label = axis_labels[idx] if idx < 3 else col
                channel_has_static.append(ch_label)
                all_segments.extend(segments)
                for start, end in segments:
                    static_mask.iloc[start : end + 1] = True

        if all_segments:
            report.static_count = len(all_segments)
            if len(channel_has_static) == 3:
                report.static_channels = "XYZ"
            else:
                report.static_channels = ",".join(channel_has_static)
            first_idx = min(s[0] for s in all_segments)
            report.static_first_frame = int(frame_ids.iloc[first_idx])
            report.static_max_duration = max(end - start + 1 for start, end in all_segments)

        return static_mask

    def _check_acc_cyclic(
        self,
        acc_df: pd.DataFrame,
        static_mask: pd.Series,
        frame_ids: pd.Series,
        report: AccAnomalyReport,
    ) -> None:
        """检测固定序列重复（周期2~50，≥2个完整周期），排除静止段"""
        channel_has_cyclic: List[str] = []
        all_segments: List[Tuple[int, int]] = []
        axis_labels = ["X", "Y", "Z"]

        for idx, col in enumerate(acc_df.columns):
            values = acc_df[col].values.copy()
            mask = ~static_mask.values
            segments = self._find_cyclic_segments(values, mask)
            if segments:
                ch_label = axis_labels[idx] if idx < 3 else col
                channel_has_cyclic.append(ch_label)
                all_segments.extend(segments)

        if all_segments:
            report.cyclic_count = len(all_segments)
            if len(channel_has_cyclic) == 3:
                report.cyclic_channels = "XYZ"
            else:
                report.cyclic_channels = ",".join(channel_has_cyclic)
            first_idx = min(s[0] for s in all_segments)
            report.cyclic_first_frame = int(frame_ids.iloc[first_idx])
            report.cyclic_max_duration = max(end - start + 1 for start, end in all_segments)

    @staticmethod
    def _find_consecutive_segments(mask: pd.Series, min_length: int = 1) -> List[Tuple[int, int]]:
        """找到布尔掩码中连续True的段落，返回(start_idx, end_idx)列表"""
        if mask.sum() == 0:
            return []

        segments: List[Tuple[int, int]] = []
        in_segment = False
        start = 0

        for i, val in enumerate(mask.values):
            if val and not in_segment:
                in_segment = True
                start = i
            elif not val and in_segment:
                in_segment = False
                length = i - start
                if length >= min_length:
                    segments.append((start, i - 1))
        if in_segment:
            length = len(mask) - start
            if length >= min_length:
                segments.append((start, len(mask) - 1))

        return segments

    @staticmethod
    def _find_cyclic_segments(
        values: np.ndarray, valid_mask: np.ndarray, min_period: int = 2, max_period: int = 50
    ) -> List[Tuple[int, int]]:
        """在一维数组中检测固定序列重复(≥2个完整周期)，只在valid_mask为True的区域检测"""
        n = len(values)
        segments: List[Tuple[int, int]] = []
        i = 0

        while i < n - min_period * 2:
            if not valid_mask[i]:
                i += 1
                continue

            found = False
            for p in range(min_period, min(max_period + 1, (n - i) // 2 + 1)):
                if not all(valid_mask[i : i + p]):
                    continue
                pattern = values[i : i + p]
                if np.all(pattern == pattern[0]):
                    break

                repeats = 1
                j = i + p
                while j + p <= n and np.array_equal(values[j : j + p], pattern):
                    repeats += 1
                    j += p

                if repeats >= 2:
                    segments.append((i, j - 1))
                    i = j
                    found = True
                    break

            if not found:
                i += 1

        return segments
