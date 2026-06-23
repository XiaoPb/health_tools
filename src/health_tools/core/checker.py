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

    @property
    def has_anomaly(self) -> bool:
        return any(
            a.count > 0
            for a in [
                self.zero,
                self.static_x,
                self.static_y,
                self.static_z,
                self.static_xyz,
                self.cyclic_x,
                self.cyclic_y,
                self.cyclic_z,
                self.cyclic_xyz,
            ]
        )


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

    def _get_ipd_columns(self) -> List[str]:
        """获取Ipd列名：优先check_columns.ipd，其次从columns匹配"""
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
        explicit = self.chip_rule.check_columns.get("agc")
        if explicit:
            return explicit
        columns = self.chip_rule.columns or []
        expanded = expand_columns(columns)
        agc_cols = [c for c in expanded if re.match(r"(?i)^agc[_\s]?info\d*$", c)]
        if agc_cols:
            return agc_cols
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
        col_names = ", ".join(abnormal_cols)
        return CheckResult(
            "数据范围",
            False,
            f"{len(abnormal_cols)}/{len(data_cols)} 列超范围 [{col_names}], "
            f"共 {total_abnormal} 个异常值 ({pct:.1f}%)",
            details,
        )

    def check_frame_completeness(self, df: pd.DataFrame) -> CheckResult:
        """检查帧号是否完整（丢包检测）"""
        frame_col = self._resolve_frame_column(df)
        if not frame_col:
            return CheckResult("帧完整性", False, "未找到帧号列")

        frame_ids = pd.to_numeric(df[frame_col], errors="coerce").dropna().astype(int)
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

        col_names = ", ".join(off_center_cols)
        return CheckResult(
            "数据居中",
            False,
            f"{len(off_center_cols)}/{len(data_cols)} 列偏离居中 [{col_names}]",
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

            gain_k = self._extract_gain_k_series(df, agc_cols, i, gain_map)

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

        col_names = ", ".join(mismatch_cols)
        return CheckResult(
            "Ipd转换",
            False,
            f"{len(mismatch_cols)}/{check_count} 通道超差 [{col_names}]",
            details,
        )

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

        agc_data = pd.to_numeric(df[agc_cols[ch_index]], errors="coerce")
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
        per_ch_static = self._check_acc_static(acc_df, frame_ids, report)
        self._check_acc_cyclic(acc_df, per_ch_static, frame_ids, report)

        return report

    def _check_acc_all_zero(
        self, acc_df: pd.DataFrame, frame_ids: pd.Series, report: AccAnomalyReport
    ) -> None:
        """检测XYZ同时为0的连续段"""
        all_zero = (acc_df == 0).all(axis=1)
        segments = self._find_consecutive_segments(all_zero)
        if segments:
            report.zero = AccChannelAnomaly(
                count=len(segments),
                first_frame=int(frame_ids.iloc[segments[0][0]]),
                max_duration=max(end - start + 1 for start, end in segments),
                frames=[int(frame_ids.iloc[s[0]]) for s in segments],
            )

    def _check_acc_static(
        self, acc_df: pd.DataFrame, frame_ids: pd.Series, report: AccAnomalyReport
    ) -> Dict[str, pd.Series]:
        """检测连续不变段落，三通道都有→归XYZ，否则归单通道"""
        per_ch_static: Dict[str, pd.Series] = {}
        per_ch_segments: Dict[int, List[Tuple[int, int]]] = {}

        for idx, col in enumerate(acc_df.columns):
            ch_mask = pd.Series(False, index=acc_df.index)
            series = acc_df[col]
            unchanged = series.diff().eq(0)
            unchanged.iloc[0] = False
            segments = self._find_consecutive_segments(unchanged, min_length=self.static_min)
            if segments:
                for start, end in segments:
                    ch_mask.iloc[start : end + 1] = True
            per_ch_static[col] = ch_mask
            per_ch_segments[idx] = segments

        has_x = len(per_ch_segments.get(0, [])) > 0
        has_y = len(per_ch_segments.get(1, [])) > 0
        has_z = len(per_ch_segments.get(2, [])) > 0

        if has_x and has_y and has_z:
            # 三通道都有静止→找同时静止的帧段（三通道mask交集）
            cols = list(acc_df.columns)
            combined_mask = (
                per_ch_static[cols[0]] & per_ch_static[cols[1]] & per_ch_static[cols[2]]
            )
            xyz_segs = self._find_consecutive_segments(combined_mask, min_length=1)
            if xyz_segs:
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
                    targets[idx].count = len(segs)
                    targets[idx].first_frame = int(frame_ids.iloc[segs[0][0]])
                    targets[idx].max_duration = max(end - start + 1 for start, end in segs)
                    targets[idx].frames = [int(frame_ids.iloc[s[0]]) for s in segs]

        return per_ch_static

    def _check_acc_cyclic(
        self,
        acc_df: pd.DataFrame,
        per_ch_static: Dict[str, pd.Series],
        frame_ids: pd.Series,
        report: AccAnomalyReport,
    ) -> None:
        """检测固定序列重复，三通道都有→归XYZ，否则归单通道"""
        per_ch_segments: Dict[int, List[Tuple[int, int]]] = {}

        for idx, col in enumerate(acc_df.columns):
            values = acc_df[col].values.copy()
            ch_static = per_ch_static.get(col, pd.Series(False, index=acc_df.index))
            mask = ~ch_static.values
            segments = self._find_cyclic_segments(values, mask)
            per_ch_segments[idx] = segments

        has_x = len(per_ch_segments.get(0, [])) > 0
        has_y = len(per_ch_segments.get(1, [])) > 0
        has_z = len(per_ch_segments.get(2, [])) > 0

        if has_x and has_y and has_z:
            # 三通道都有循环→合并去重（按起始帧去重）
            all_segs = per_ch_segments[0] + per_ch_segments[1] + per_ch_segments[2]
            seen_starts = set()
            unique_segs = []
            for s in sorted(all_segs, key=lambda s: s[0]):
                if s[0] not in seen_starts:
                    seen_starts.add(s[0])
                    unique_segs.append(s)
            report.cyclic_xyz = AccChannelAnomaly(
                count=len(unique_segs),
                first_frame=int(frame_ids.iloc[unique_segs[0][0]]),
                max_duration=max(end - start + 1 for start, end in unique_segs),
                frames=[int(frame_ids.iloc[s[0]]) for s in unique_segs],
            )
        else:
            targets = [report.cyclic_x, report.cyclic_y, report.cyclic_z]
            for idx, segs in per_ch_segments.items():
                if idx < 3 and segs:
                    targets[idx].count = len(segs)
                    targets[idx].first_frame = int(frame_ids.iloc[segs[0][0]])
                    targets[idx].max_duration = max(end - start + 1 for start, end in segs)
                    targets[idx].frames = [int(frame_ids.iloc[s[0]]) for s in segs]

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
        values: np.ndarray,
        valid_mask: np.ndarray,
        min_period: int = 2,
        max_period: int = 50,
        min_amplitude: int = 20,
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
                if pattern.max() - pattern.min() < min_amplitude:
                    continue

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
