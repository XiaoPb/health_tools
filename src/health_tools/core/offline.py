"""离线跑库核心逻辑"""

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

from health_tools.config import CONFIG_DIR, load_config, save_config
from health_tools.utils.accuracy import calculate_accuracy

OFFLINE_TOOLS_DIR = CONFIG_DIR / "offline_algorithm_tools"
EXE_NAME = "TEE_Algorithm.exe"

DEFAULT_COLUMN_INDICES = {
    "gh3036": {
        "accx": 2,
        "accy": 3,
        "accz": 4,
        "ppg_ch0": 5,
        "ppg_ch1": 6,
        "ppg_ch2": 7,
        "ppg_ch3": 8,
        "polar": 45,
        "mcu_out": 61,
        "comp_out": 46,
    },
    "gh3220": {
        "accx": 2,
        "accy": 3,
        "accz": 4,
        "ppg_ch0": 5,
        "ppg_ch1": 6,
        "ppg_ch2": 7,
        "ppg_ch3": 8,
        "polar": 37,
        "mcu_out": 53,
        "comp_out": 38,
    },
}


@dataclass
class OfflineConfig:
    """离线跑库配置"""

    tools_path: Path = field(default_factory=lambda: OFFLINE_TOOLS_DIR)
    versions: Dict[str, dict] = field(default_factory=dict)


def get_offline_config() -> OfflineConfig:
    config = load_config()
    tools_path = Path(config.get("offline_tools_path", str(OFFLINE_TOOLS_DIR)))
    versions = config.get("offline_versions", {})
    return OfflineConfig(tools_path=tools_path, versions=versions)


def scan_versions(tools_path: Optional[Path] = None) -> Dict[str, dict]:
    """扫描离线工具目录，发现所有芯片和版本"""
    if tools_path is None:
        tools_path = get_offline_config().tools_path
    if not tools_path.exists():
        return {}

    result = {}
    for chip_dir in sorted(tools_path.iterdir()):
        if not chip_dir.is_dir():
            continue
        chip_name = chip_dir.name
        exclusive_dir = chip_dir / "exclusive"
        if not exclusive_dir.exists():
            continue

        versions = []
        for ver_dir in sorted(exclusive_dir.iterdir()):
            if not ver_dir.is_dir():
                continue
            exe_path = ver_dir / EXE_NAME
            if exe_path.exists():
                versions.append(ver_dir.name)

        if versions:
            result[chip_name] = {
                "versions": versions,
                "default": versions[-1],
            }

    return result


def save_offline_config(tools_path: Path, versions: Dict[str, dict]) -> None:
    """保存离线工具配置到 config.yaml"""
    config = load_config()
    config["offline_tools_path"] = str(tools_path)
    config["offline_versions"] = versions
    save_config(config)


def find_exe(chip: str, version: Optional[str] = None) -> Optional[Path]:
    """查找指定芯片和版本的 exe 路径"""
    cfg = get_offline_config()
    if version is None:
        chip_cfg = cfg.versions.get(chip, {})
        version = chip_cfg.get("default")
        if not version:
            return None

    exe_path = cfg.tools_path / chip / "exclusive" / version / EXE_NAME
    return exe_path if exe_path.exists() else None


def list_versions(chip: Optional[str] = None) -> Dict[str, dict]:
    """列出已配置的版本信息"""
    cfg = get_offline_config()
    if chip:
        chip_cfg = cfg.versions.get(chip)
        return {chip: chip_cfg} if chip_cfg else {}
    return cfg.versions


class OfflineRunner:
    """离线跑库执行器"""

    def __init__(
        self,
        chip: str,
        version: Optional[str] = None,
        hba_fs: int = 25,
        scene_en: int = 0,
        ch_num: int = 2,
        column_indices: Optional[Dict[str, int]] = None,
    ):
        self.chip = chip
        self.version = version
        self.hba_fs = hba_fs
        self.scene_en = scene_en
        self.ch_num = ch_num
        self.column_indices = column_indices or DEFAULT_COLUMN_INDICES.get(chip, {})

        self.exe_path = find_exe(chip, version)
        if self.exe_path:
            self.tool_dir = self.exe_path.parent
        else:
            self.tool_dir = None

    def _build_command(self, input_dir: str, output_dir: str) -> str:
        """构建 exe 命令行"""
        exe = str(self.exe_path)
        idx = self.column_indices

        if self.chip.startswith("gh3036"):
            debug_para = (
                f"{idx.get('accx', 2)} {idx.get('accy', 3)} {idx.get('accz', 4)} "
                f"{idx.get('ppg_ch0', 5)} {idx.get('ppg_ch1', 6)} "
                f"{idx.get('ppg_ch2', 7)} {idx.get('ppg_ch3', 8)} "
                f"{idx.get('polar', 45)} {idx.get('mcu_out', 61)} "
                f"{idx.get('comp_out', 46)}"
            )
            cmd = (
                f'"{exe}" 0 -1 "{input_dir}" "{output_dir}" csv '
                f"{self.hba_fs} {self.scene_en} {self.ch_num} {debug_para}"
            )
        else:
            cmd = (
                f'"{exe}" 0 -1 "{input_dir}" "{output_dir}" csv '
                f"0 {self.scene_en} {self.hba_fs} 0"
            )
        return cmd

    def run(self, input_dir: Path, output_dir: Path, timeout: int = 300) -> bool:
        """执行离线跑库

        Args:
            input_dir: 输入数据目录（GH格式CSV）
            output_dir: 输出结果目录
            timeout: 超时时间（秒）

        Returns:
            是否成功
        """
        if not self.exe_path or not self.tool_dir:
            return False

        input_str = str(input_dir.resolve())
        output_str = str(output_dir.resolve())

        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        cmd = self._build_command(input_str, output_str)
        old_cwd = os.getcwd()
        os.chdir(str(self.tool_dir))
        try:
            result = subprocess.run(cmd, shell=True, timeout=timeout)
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            return False
        finally:
            os.chdir(old_cwd)


class VshbParser:
    """解析 _result.vshb 文件"""

    COL_TIME = 0
    COL_OFFLINE = 1
    COL_REF = 2
    COL_ONLINE = 30

    def parse(self, vshb_path: Path) -> pd.DataFrame:
        """解析vshb为DataFrame，列名: time, offline, ref, online"""
        df = pd.read_csv(vshb_path, header=None)
        if df.shape[1] <= self.COL_ONLINE:
            return pd.DataFrame(columns=["time", "offline", "ref", "online"])
        result = pd.DataFrame(
            {
                "time": pd.to_numeric(df.iloc[:, self.COL_TIME], errors="coerce"),
                "offline": pd.to_numeric(df.iloc[:, self.COL_OFFLINE], errors="coerce"),
                "ref": pd.to_numeric(df.iloc[:, self.COL_REF], errors="coerce"),
                "online": pd.to_numeric(df.iloc[:, self.COL_ONLINE], errors="coerce"),
            }
        )
        return result[result["ref"] > 0].reset_index(drop=True)


ACCURACY_METHODS = ["mae", "within_5", "within_10", "rmse", "correlation"]


def calculate_offline_accuracy(
    output_dir: Path,
) -> Tuple[Optional[pd.DataFrame], Dict[str, pd.DataFrame]]:
    """计算离线跑库准确度

    Args:
        output_dir: 离线跑库输出根目录

    Returns:
        (summary_df, per_file_dict): 汇总DataFrame和每个文件的详细DataFrame
    """
    vshb_files = sorted(output_dir.rglob("*_result.vshb"))
    if not vshb_files:
        return None, {}

    parser = VshbParser()
    category_data: Dict[str, List[Dict]] = {}
    per_file: Dict[str, pd.DataFrame] = {}

    for vshb_path in vshb_files:
        df = parser.parse(vshb_path)
        if df.empty:
            continue

        rel = vshb_path.relative_to(output_dir)
        category = rel.parts[0] if len(rel.parts) > 1 else "default"
        per_file[str(rel)] = df

        offline_metrics = calculate_accuracy(df, "ref", "offline", ACCURACY_METHODS)
        online_metrics = calculate_accuracy(df, "ref", "online", ACCURACY_METHODS)

        entry = {
            "file": vshb_path.stem.replace("_result", ""),
            "category": category,
            "samples": offline_metrics.get("samples", 0),
        }
        for key, val in offline_metrics.items():
            if key != "samples":
                entry[f"offline_{key}"] = val
        for key, val in online_metrics.items():
            if key != "samples":
                entry[f"online_{key}"] = val

        category_data.setdefault(category, []).append(entry)

    if not category_data:
        return None, per_file

    all_rows = []
    all_rows = []
    for entries in category_data.values():
        all_rows.extend(entries)

    summary_rows = []
    total_samples = 0
    total_metrics: Dict[str, float] = {}

    for category, entries in sorted(category_data.items()):
        cat_df = pd.DataFrame(entries)
        samples = int(cat_df["samples"].sum())
        total_samples += samples
        row = {"category": category, "files": len(entries), "samples": samples}

        for col in cat_df.columns:
            if col.startswith(("offline_", "online_")) and col not in row:
                weighted = (cat_df[col] * cat_df["samples"]).sum()
                avg = weighted / samples if samples > 0 else 0.0
                row[col] = round(avg, 2)
                total_metrics[col] = total_metrics.get(col, 0.0) + weighted

        summary_rows.append(row)

    total_row = {
        "category": "TOTAL",
        "files": sum(len(e) for e in category_data.values()),
        "samples": total_samples,
    }
    for col, weighted_sum in total_metrics.items():
        total_row[col] = round(weighted_sum / total_samples, 2) if total_samples > 0 else 0.0

    summary_rows.insert(0, total_row)
    summary_df = pd.DataFrame(summary_rows)

    return summary_df, per_file
