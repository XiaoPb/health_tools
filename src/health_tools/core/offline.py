"""离线跑库核心逻辑"""

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from health_tools.config import CONFIG_DIR, load_config, save_config
from health_tools.utils.accuracy import calculate_accuracy, format_metric_name

OFFLINE_TOOLS_DIR = CONFIG_DIR / "offline_algorithm_tools"
EXE_NAME = "TEE_Algorithm.exe"

# 目录名 → 标准算法等级名
CATEGORY_LABELS = {
    "性能版本": "exclusive",
    "exclusive": "exclusive",
    "premium": "premium",
    "medium": "medium",
    "basic": "basic",
}


def get_category_label(cat: str) -> str:
    return CATEGORY_LABELS.get(cat, cat)

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
    """扫描离线工具目录，发现所有芯片和版本（遍历所有子目录类别）"""
    if tools_path is None:
        tools_path = get_offline_config().tools_path
    if not tools_path.exists():
        return {}

    result = {}
    for chip_dir in sorted(tools_path.iterdir()):
        if not chip_dir.is_dir():
            continue
        chip_name = chip_dir.name
        categories: Dict[str, List[str]] = {}
        last_version = ""

        for category_dir in sorted(chip_dir.iterdir()):
            if not category_dir.is_dir():
                continue
            category_name = category_dir.name
            versions = []
            for ver_dir in sorted(category_dir.iterdir()):
                if not ver_dir.is_dir():
                    continue
                exe_path = ver_dir / EXE_NAME
                if exe_path.exists():
                    versions.append(ver_dir.name)
            if versions:
                categories[category_name] = versions
                last_version = versions[-1]

        if categories:
            first_category = next(iter(categories))
            result[chip_name] = {
                "versions": categories,
                "default": last_version,
                "default_category": first_category,
            }

    return result


def save_offline_config(tools_path: Path, versions: Dict[str, dict]) -> None:
    """保存离线工具配置到 config.yaml"""
    config = load_config()
    config["offline_tools_path"] = str(tools_path)
    config["offline_versions"] = versions
    save_config(config)


def find_exe(chip: str, version: Optional[str] = None) -> Optional[Path]:
    """查找指定芯片和版本的 exe 路径（搜索所有类别目录）"""
    cfg = get_offline_config()
    chip_cfg = cfg.versions.get(chip, {})
    if version is None:
        version = chip_cfg.get("default")
        if not version:
            return None

    versions_data = chip_cfg.get("versions", {})
    if isinstance(versions_data, dict):
        for category, ver_list in versions_data.items():
            if version in ver_list:
                exe_path = cfg.tools_path / chip / category / version / EXE_NAME
                if exe_path.exists():
                    return exe_path
    elif isinstance(versions_data, list):
        exe_path = cfg.tools_path / chip / "exclusive" / version / EXE_NAME
        if exe_path.exists():
            return exe_path

    chip_dir = cfg.tools_path / chip
    if chip_dir.exists():
        for category_dir in chip_dir.iterdir():
            if not category_dir.is_dir():
                continue
            exe_path = category_dir / version / EXE_NAME
            if exe_path.exists():
                return exe_path
    return None


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


RESULT_EXTENSIONS = [
    "_result.vshb",
    ".prepsd",
    ".accxpsd",
    ".accypsd",
    ".acczpsd",
    ".accrmspsd",
]

# exe输出文件名前缀格式: 数字序号_原始文件名
_EXE_PREFIX_SEP = "_"


def _strip_exe_prefix(name: str) -> str:
    """去掉exe输出文件名的序号前缀，如 '000000_动态-夏-158' -> '动态-夏-158'"""
    idx = name.find(_EXE_PREFIX_SEP)
    if idx > 0 and name[:idx].isdigit():
        return name[idx + 1 :]
    return name


def reorganize_output(input_dir: Path, output_dir: Path) -> Path:
    """按输入目录的子目录结构重新整理输出文件

    将 output_dir 根目录下平铺的结果文件，按源 CSV 所在子目录归类到
    {output_dir}/数据整理/{子目录}/ 下。仅整理能匹配到源 CSV 的文件。

    Returns:
        整理后的根目录路径
    """
    reorg_dir = output_dir / "数据整理"

    source_map: Dict[str, str] = {}
    for csv_file in input_dir.rglob("*.csv"):
        rel = csv_file.relative_to(input_dir)
        subdir = str(rel.parent) if len(rel.parts) > 1 else ""
        source_map[csv_file.stem] = subdir

    for result_file in output_dir.iterdir():
        if not result_file.is_file():
            continue
        stem = result_file.stem
        for ext in RESULT_EXTENSIONS:
            if result_file.name.endswith(ext):
                stem = result_file.name[: -len(ext)]
                break

        bare_stem = _strip_exe_prefix(stem)

        matched_key = None
        if bare_stem in source_map:
            matched_key = bare_stem
        else:
            for csv_stem in source_map:
                if bare_stem.startswith(csv_stem) or csv_stem.startswith(bare_stem):
                    matched_key = csv_stem
                    break

        if matched_key is None:
            continue

        subdir = source_map[matched_key]
        target_dir = reorg_dir / subdir if subdir else reorg_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(result_file), str(target_dir / result_file.name))

    return reorg_dir


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
) -> Optional[pd.DataFrame]:
    """计算离线跑库准确度

    输出格式：每个文件一行，然后分类平均行，最后TOTAL行。

    Args:
        output_dir: 离线跑库输出根目录

    Returns:
        完整报告DataFrame（含文件行+分类汇总+整体汇总）
    """
    vshb_files = sorted(output_dir.rglob("*_result.vshb"))
    if not vshb_files:
        return None

    parser = VshbParser()
    file_rows: List[Dict] = []

    for vshb_path in vshb_files:
        df = parser.parse(vshb_path)
        if df.empty:
            continue

        rel = vshb_path.relative_to(output_dir)
        category = rel.parts[0] if len(rel.parts) > 1 else "default"

        offline_metrics = calculate_accuracy(df, "ref", "offline", ACCURACY_METHODS)
        online_metrics = calculate_accuracy(df, "ref", "online", ACCURACY_METHODS)

        row: Dict = {
            "file": vshb_path.stem.replace("_result", ""),
            "category": category,
            "samples": offline_metrics.get("samples", 0),
        }
        for key, val in offline_metrics.items():
            if key != "samples":
                row[f"{format_metric_name(key)}(offline)"] = round(val, 2)
        for key, val in online_metrics.items():
            if key != "samples":
                row[f"{format_metric_name(key)}(online)"] = round(val, 2)

        file_rows.append(row)

    if not file_rows:
        return None

    # 按分类分组计算加权平均
    category_data: Dict[str, List[Dict]] = {}
    for row in file_rows:
        category_data.setdefault(row["category"], []).append(row)

    metric_cols = [c for c in file_rows[0] if c not in ("file", "category", "samples")]
    summary_rows: List[Dict] = []

    total_samples = 0
    total_weighted: Dict[str, float] = {col: 0.0 for col in metric_cols}

    for category, entries in sorted(category_data.items()):
        cat_samples = sum(e["samples"] for e in entries)
        total_samples += cat_samples
        cat_row: Dict = {
            "file": f"{category}(avg)",
            "category": category,
            "samples": cat_samples,
        }
        for col in metric_cols:
            weighted = sum(e[col] * e["samples"] for e in entries)
            total_weighted[col] += weighted
            cat_row[col] = round(weighted / cat_samples, 2) if cat_samples > 0 else 0.0
        summary_rows.append(cat_row)

    total_row: Dict = {
        "file": "TOTAL",
        "category": "",
        "samples": total_samples,
    }
    for col in metric_cols:
        total_row[col] = round(total_weighted[col] / total_samples, 2) if total_samples > 0 else 0.0
    summary_rows.append(total_row)

    all_rows = file_rows + summary_rows
    return pd.DataFrame(all_rows)
