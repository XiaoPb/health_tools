"""离线跑库核心逻辑"""

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd
import yaml

from health_tools.config import CONFIG_DIR, load_config, save_config
from health_tools.rules.loader import RuleLoader
from health_tools.utils.accuracy import calculate_accuracy, format_metric_name
from health_tools.utils.progress import progress_track
from health_tools.core.vshb import read_vshb_result

OFFLINE_TOOLS_DIR = CONFIG_DIR / "offline_algorithm_tools"
EXE_NAME = "TEE_Algorithm.exe"
LOCAL_CMD_CONFIG_NAME = "cmd_setting.yaml"


class OfflineConfigError(ValueError):
    """离线工具参数配置错误。"""


def load_local_cmd_config(tool_dir: Path) -> Optional[dict]:
    """读取exe同目录参数配置；文件存在时整份替换全局配置。"""
    config_path = tool_dir / LOCAL_CMD_CONFIG_NAME
    if not config_path.exists():
        return None

    try:
        with open(config_path, "r", encoding="utf-8") as file:
            config = yaml.safe_load(file)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise OfflineConfigError(f"无法读取 {config_path}: {exc}") from exc

    if not isinstance(config, dict):
        raise OfflineConfigError(f"{config_path} 根节点必须是对象")
    cmd_arg = config.get("cmd_arg")
    if not isinstance(cmd_arg, list) or not cmd_arg:
        raise OfflineConfigError(f"{config_path} 的 cmd_arg 必须是非空列表")
    cmd_default = config.get("cmd_default", {})
    if not isinstance(cmd_default, dict):
        raise OfflineConfigError(f"{config_path} 的 cmd_default 必须是对象")
    return {"cmd_arg": cmd_arg, "cmd_default": cmd_default}


# 目录名 → 标准算法等级名
CATEGORY_LABELS = {
    "性能版本": "exclusive",
    "exclusive": "exclusive",
    "premium": "premium",
    "med": "medium",
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
    commands: Dict[str, dict] = field(default_factory=dict)


@dataclass
class OfflineRunResult:
    """离线工具执行结果。"""

    success: bool
    command: str = ""
    returncode: Optional[int] = None
    timed_out: bool = False
    started_at: float = 0.0
    ended_at: float = 0.0
    input_count: int = 0
    result_count: int = 0
    output_file_count: int = 0
    last_output_mtime: Optional[float] = None
    warning: Optional[str] = None
    error: Optional[str] = None

    @property
    def duration(self) -> float:
        return max(0.0, self.ended_at - self.started_at)

    @property
    def missing_count(self) -> int:
        return max(0, self.input_count - self.result_count)


def get_offline_config() -> OfflineConfig:
    config = load_config()
    tools_path = Path(config.get("offline_tools_path", str(OFFLINE_TOOLS_DIR)))
    versions = config.get("offline_versions", {})
    commands = config.get("offline_cmd", {})
    return OfflineConfig(tools_path=tools_path, versions=versions, commands=commands)


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


def _iter_versions(chip_info: dict) -> List[str]:
    """展开芯片版本配置中的版本列表。"""
    versions_data = chip_info.get("versions", {})
    if isinstance(versions_data, dict):
        return [v for ver_list in versions_data.values() for v in ver_list]
    if isinstance(versions_data, list):
        return versions_data
    return []


def _find_version_category(chip_info: dict, version: str) -> Optional[str]:
    versions_data = chip_info.get("versions", {})
    if isinstance(versions_data, dict):
        for category, ver_list in versions_data.items():
            if version in ver_list:
                return category
    elif isinstance(versions_data, list) and version in versions_data:
        return "exclusive"
    return None


def merge_scanned_versions(scanned: Dict[str, dict], existing: Dict[str, dict]) -> Dict[str, dict]:
    """合并扫描结果，保留仍然有效的用户默认版本。"""
    merged = {}
    for chip, scanned_info in scanned.items():
        info = dict(scanned_info)
        old_info = existing.get(chip, {}) if isinstance(existing, dict) else {}
        old_default = old_info.get("default") if isinstance(old_info, dict) else None

        if isinstance(old_info, dict):
            for key, value in old_info.items():
                if key not in {"versions", "default", "default_category"}:
                    info[key] = value

        if old_default and old_default in _iter_versions(info):
            info["default"] = old_default
            old_category = old_info.get("default_category")
            if old_category and old_default in info.get("versions", {}).get(old_category, []):
                info["default_category"] = old_category
            else:
                found_category = _find_version_category(info, old_default)
                if found_category:
                    info["default_category"] = found_category
        merged[chip] = info
    return merged


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


def _normalize_cmd_arg(value: object) -> str:
    """规范化 cmd_arg 变量名，支持 {polar} 写法。"""
    key = str(value)
    if key.startswith("{") and key.endswith("}"):
        key = key[1:-1]
    return key


def _default_indices_for_chip(chip: str) -> Dict[str, int]:
    """按芯片名获取内置默认列号。"""
    if chip in DEFAULT_COLUMN_INDICES:
        return dict(DEFAULT_COLUMN_INDICES[chip])
    for prefix, indices in DEFAULT_COLUMN_INDICES.items():
        if chip.startswith(prefix):
            return dict(indices)
    return {}


def _match_first_index(column_index: Dict[str, int], patterns: List[str]) -> Optional[int]:
    """按正则列表返回第一个匹配列号。"""
    for pattern in patterns:
        regex = re.compile(pattern, re.IGNORECASE)
        for name, index in column_index.items():
            if regex.fullmatch(name):
                return index
    return None


def _find_ppg_indices(column_index: Dict[str, int]) -> List[int]:
    """从展开后的列名中推导前4个PPG通道列号。"""
    ppg_patterns = [
        r"ipd\d+",
        r"ch\d+",
        r"slotcfg\d+rx\d+",
        r"rawdata\d+",
    ]
    for pattern in ppg_patterns:
        regex = re.compile(pattern, re.IGNORECASE)
        matched = [
            (index, name)
            for name, index in column_index.items()
            if regex.fullmatch(name)
            and not re.search(r"agc|led|physics|amb|cap|flag", name, re.IGNORECASE)
        ]
        matched.sort()
        if len(matched) >= 4:
            return [index for index, _ in matched[:4]]
    return []


def build_column_indices(chip: str) -> Dict[str, int]:
    """从芯片规则推导离线工具列号，失败时使用内置默认值。"""
    indices = _default_indices_for_chip(chip)
    try:
        rule = RuleLoader.load_chip_rule(chip)
    except Exception:
        return indices

    columns = RuleLoader.expand_columns(rule.columns)
    column_index = {name: pos for pos, name in enumerate(columns)}

    for key, patterns in {
        "accx": [r"accx", r"acc_x"],
        "accy": [r"accy", r"acc_y"],
        "accz": [r"accz", r"acc_z"],
        "mcu_out": [r"algo_result0"],
        "comp_out": [r"ref_result1"],
    }.items():
        matched = _match_first_index(column_index, patterns)
        if matched is not None:
            indices[key] = matched

    ppg_indices = _find_ppg_indices(column_index)
    for idx, column_pos in enumerate(ppg_indices[:4]):
        indices[f"ppg_ch{idx}"] = column_pos

    if rule.hr_ref_column:
        first_ref = next(iter(rule.hr_ref_column.values()))
        if first_ref is not None:
            indices["polar"] = int(first_ref) - 1
    else:
        matched_ref = _match_first_index(column_index, [r"ref_result0"])
        if matched_ref is not None:
            indices["polar"] = matched_ref

    return indices


class OfflineRunner:
    """离线跑库执行器"""

    def __init__(
        self,
        chip: str,
        version: Optional[str] = None,
        hba_fs: Optional[int] = None,
        scene_en: Optional[int] = None,
        ch_num: Optional[int] = None,
        column_indices: Optional[Dict[str, int]] = None,
    ):
        self.chip = chip
        self.version = version
        self.hba_fs = hba_fs
        self.scene_en = scene_en
        self.ch_num = ch_num
        self.column_indices = build_column_indices(chip)
        if column_indices:
            self.column_indices.update(column_indices)

        self.exe_path = find_exe(chip, version)
        if self.exe_path:
            self.tool_dir = self.exe_path.parent
            self.resolved_version = self.exe_path.parent.name
        else:
            self.tool_dir = None
            self.resolved_version = version

    def _get_cmd_config(self) -> dict:
        """获取当前芯片和算法版本的命令模板配置。"""
        local_config = self._load_local_cmd_config()
        if local_config is not None:
            return local_config

        if not self.resolved_version:
            return {}
        cfg = get_offline_config()
        chip_cmd = cfg.commands.get(self.chip, {})
        if not isinstance(chip_cmd, dict):
            chip_cmd = {}
        cmd_cfg = chip_cmd.get(self.resolved_version, {})
        if isinstance(cmd_cfg, dict) and cmd_cfg:
            return cmd_cfg

        chip_version_cfg = cfg.versions.get(self.chip, {})
        if not isinstance(chip_version_cfg, dict):
            return {}

        version_cmds = chip_version_cfg.get("offline_cmd", {})
        if isinstance(version_cmds, dict):
            cmd_cfg = version_cmds.get(self.resolved_version, {})
            if isinstance(cmd_cfg, dict) and cmd_cfg:
                return cmd_cfg

        if "cmd_arg" in chip_version_cfg or "cmd_default" in chip_version_cfg:
            return {
                "cmd_arg": chip_version_cfg.get("cmd_arg", []),
                "cmd_default": chip_version_cfg.get("cmd_default", {}),
            }
        return {}

    def _load_local_cmd_config(self) -> Optional[dict]:
        """读取exe同目录参数配置；文件存在时整份替换全局配置。"""
        if self.tool_dir is None:
            return None
        return load_local_cmd_config(self.tool_dir)

    def _build_command(self, input_dir: str, output_dir: str) -> str:
        """构建 exe 命令行"""
        exe = str(self.exe_path)
        cmd_cfg = self._get_cmd_config()
        cmd_arg = cmd_cfg.get("cmd_arg", [])
        if isinstance(cmd_arg, list) and cmd_arg:
            args = [exe]
            values = self._build_template_values(input_dir, output_dir, cmd_cfg)
            for item in cmd_arg:
                key = _normalize_cmd_arg(item)
                args.append(str(values.get(key, item)))
            return subprocess.list2cmdline(args)

        idx = self.column_indices
        hba_fs = self.hba_fs if self.hba_fs is not None else 25
        scene_en = self.scene_en if self.scene_en is not None else 0
        ch_num = self.ch_num if self.ch_num is not None else 2

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
                f"{hba_fs} {scene_en} {ch_num} {debug_para}"
            )
        else:
            cmd = f'"{exe}" 0 -1 "{input_dir}" "{output_dir}" csv ' f"0 {scene_en} {hba_fs} 0"
        return cmd

    def _build_template_values(
        self, input_dir: str, output_dir: str, cmd_cfg: dict
    ) -> Dict[str, Union[int, str]]:
        """构建 cmd_arg 变量表。"""
        defaults = cmd_cfg.get("cmd_default", {})
        if not isinstance(defaults, dict):
            defaults = {}

        values: Dict[str, Union[int, str]] = dict(defaults)
        values.update(
            {
                "input_dir": input_dir,
                "output_dir": output_dir,
            }
        )
        values["hba_fs"] = self.hba_fs if self.hba_fs is not None else defaults.get("hba_fs", 25)
        values["scene_en"] = (
            self.scene_en if self.scene_en is not None else defaults.get("scene_en", 0)
        )
        values["ch_num"] = self.ch_num if self.ch_num is not None else defaults.get("ch_num", 2)
        values.update(self.column_indices)
        return values

    def run(
        self,
        input_dir: Path,
        output_dir: Path,
        timeout: int = 300,
        settle_timeout: int = 10,
    ) -> OfflineRunResult:
        """执行离线跑库

        Args:
            input_dir: 输入数据目录（GH格式CSV）
            output_dir: 输出结果目录
            timeout: 超时时间（秒）
            settle_timeout: 异常返回后等待输出稳定的时间（秒）

        Returns:
            跑库执行结果
        """
        if not self.exe_path or not self.tool_dir:
            return OfflineRunResult(success=False, error="未找到离线工具")

        input_str = str(input_dir.resolve())
        output_str = str(output_dir.resolve())
        input_count = count_supported_csv_files(input_dir)

        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        cmd = self._build_command(input_str, output_str)
        old_cwd = os.getcwd()
        os.chdir(str(self.tool_dir))
        started_at = time.time()
        returncode = None
        timed_out = False
        try:
            result = subprocess.run(cmd, shell=True, timeout=timeout)
            returncode = result.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            os.chdir(old_cwd)

        if returncode == 0:
            output_file_count, result_count, last_mtime = _snapshot_output(output_dir)
        else:
            output_file_count, result_count, last_mtime = _wait_for_output_settle(
                output_dir, settle_timeout
            )

        ended_at = time.time()
        has_complete_results = input_count > 0 and result_count >= input_count
        if returncode == 0:
            success = True
            warning = None
            error = None
        elif timed_out:
            success = False
            warning = None
            error = "离线工具执行超时"
        elif has_complete_results:
            success = True
            warning = "外部工具返回异常，但结果文件已生成完整"
            error = None
        else:
            success = False
            warning = None
            error = "外部工具返回异常，且结果文件不完整"

        return OfflineRunResult(
            success=success,
            command=cmd,
            returncode=returncode,
            timed_out=timed_out,
            started_at=started_at,
            ended_at=ended_at,
            input_count=input_count,
            result_count=result_count,
            output_file_count=output_file_count,
            last_output_mtime=last_mtime,
            warning=warning,
            error=error,
        )


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


def _split_exe_prefix(name: str) -> Tuple[Optional[int], str]:
    """拆分exe输出文件名的序号前缀，如 '000000_动态-夏-158'。"""
    idx = name.find(_EXE_PREFIX_SEP)
    if idx > 0 and name[:idx].isdigit():
        return int(name[:idx]), name[idx + 1 :]
    return None, name


def _strip_exe_prefix(name: str) -> str:
    """去掉exe输出文件名的序号前缀，如 '000000_动态-夏-158' -> '动态-夏-158'"""
    return _split_exe_prefix(name)[1]


def _is_offline_tool_path_supported(path: Path) -> bool:
    """判断离线工具是否能处理该路径。"""
    try:
        str(path).encode("mbcs")
        return True
    except LookupError:
        return True
    except UnicodeEncodeError:
        return False


def count_supported_csv_files(input_dir: Path) -> int:
    """统计离线工具可处理的源CSV数量。"""
    return sum(
        1
        for csv_file in _iter_source_csv_files(input_dir)
        if _is_offline_tool_path_supported(csv_file)
    )


def _iter_source_csv_files(input_dir: Path) -> List[Path]:
    """返回扩展名大小写不敏感的源CSV。"""
    return sorted(
        path for path in input_dir.rglob("*") if path.is_file() and path.suffix.lower() == ".csv"
    )


def _snapshot_output(output_dir: Path) -> Tuple[int, int, Optional[float]]:
    """返回输出文件总数、结果文件数和最后更新时间。"""
    if not output_dir.exists():
        return 0, 0, None

    file_count = 0
    result_count = 0
    last_mtime = None
    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue
        file_count += 1
        if path.name.endswith("_result.vshb"):
            result_count += 1
        mtime = path.stat().st_mtime
        last_mtime = mtime if last_mtime is None else max(last_mtime, mtime)
    return file_count, result_count, last_mtime


def _wait_for_output_settle(
    output_dir: Path, settle_timeout: int
) -> Tuple[int, int, Optional[float]]:
    """等待输出目录停止新增或更新文件。"""
    file_count, result_count, last_mtime = _snapshot_output(output_dir)
    if settle_timeout <= 0:
        return file_count, result_count, last_mtime

    deadline = time.monotonic() + settle_timeout
    while time.monotonic() < deadline:
        time.sleep(1)
        current = _snapshot_output(output_dir)
        if current == (file_count, result_count, last_mtime):
            return current
        file_count, result_count, last_mtime = current
    return file_count, result_count, last_mtime


def _build_source_index_map(input_dir: Path) -> Dict[int, str]:
    """构建跑库输出序号到源CSV子目录的映射。"""
    source_index_map: Dict[int, str] = {}
    source_files = [
        csv_file
        for csv_file in _iter_source_csv_files(input_dir)
        if _is_offline_tool_path_supported(csv_file)
    ]
    for idx, csv_file in enumerate(source_files):
        rel = csv_file.relative_to(input_dir)
        source_index_map[idx] = str(rel.parent) if len(rel.parts) > 1 else ""
    return source_index_map


def _build_unique_source_map(input_dir: Path) -> Dict[str, str]:
    """构建无序号结果可用的唯一文件名映射。"""
    source_paths: Dict[str, List[str]] = {}
    for csv_file in _iter_source_csv_files(input_dir):
        rel = csv_file.relative_to(input_dir)
        subdir = str(rel.parent) if len(rel.parts) > 1 else ""
        source_paths.setdefault(csv_file.stem, []).append(subdir)
    return {stem: paths[0] for stem, paths in source_paths.items() if len(paths) == 1}


def reorganize_output(input_dir: Path, output_dir: Path, show_progress: bool = False) -> Path:
    """按输入目录的子目录结构重新整理输出文件

    将 output_dir 根目录下平铺的结果文件，按源 CSV 所在子目录归类到
    {output_dir}/数据整理/{子目录}/ 下。仅整理能匹配到源 CSV 的文件。

    Returns:
        整理后的根目录路径
    """
    reorg_dir = output_dir / "数据整理"

    source_map = _build_unique_source_map(input_dir)
    source_index_map = _build_source_index_map(input_dir)

    result_files = [
        path
        for path in output_dir.rglob("*")
        if path.is_file() and reorg_dir not in path.parents and path != reorg_dir
    ]
    for result_file in progress_track(result_files, "整理输出文件...", enabled=show_progress):
        if not result_file.is_file():
            continue
        stem = result_file.stem
        for ext in RESULT_EXTENSIONS:
            if result_file.name.endswith(ext):
                stem = result_file.name[: -len(ext)]
                break

        source_index, bare_stem = _split_exe_prefix(stem)

        subdir = None
        if source_index in source_index_map:
            subdir = source_index_map[source_index]
        elif bare_stem in source_map:
            subdir = source_map[bare_stem]

        if subdir is None:
            continue

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
        return read_vshb_result(vshb_path, positional_online_col=self.COL_ONLINE)


ACCURACY_METHODS = ["mae", "within_5", "within_10", "rmse", "correlation"]


def _has_valid_ref(df: pd.DataFrame) -> bool:
    """判断是否提供了有效金标心率。"""
    ref = pd.to_numeric(df["ref"], errors="coerce")
    return bool((ref > 0).any())


def _filter_valid_ref(df: pd.DataFrame) -> pd.DataFrame:
    """仅保留有效金标行。"""
    ref = pd.to_numeric(df["ref"], errors="coerce")
    return df[ref > 0].reset_index(drop=True)


def _add_metric_columns(row: Dict, metrics: Dict[str, float], suffix: str) -> None:
    """将准确度指标写入报告行。"""
    for key, val in metrics.items():
        if key != "samples":
            row[f"{format_metric_name(key)}{suffix}"] = round(val, 2)


def calculate_offline_accuracy(
    output_dir: Path,
    show_progress: bool = False,
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

    for vshb_path in progress_track(vshb_files, "统计准确度...", enabled=show_progress):
        df = parser.parse(vshb_path)
        if df.empty:
            continue

        rel = vshb_path.relative_to(output_dir)
        category = rel.parts[0] if len(rel.parts) > 1 else "default"

        has_ref = _has_valid_ref(df)
        if has_ref:
            metric_df = _filter_valid_ref(df)
            offline_metrics = calculate_accuracy(metric_df, "ref", "offline", ACCURACY_METHODS)
            online_metrics = calculate_accuracy(metric_df, "ref", "online", ACCURACY_METHODS)
            reference = "polar"
        else:
            metric_df = df
            offline_metrics = {}
            online_metrics = calculate_accuracy(metric_df, "offline", "online", ACCURACY_METHODS)
            reference = "offline"

        row: Dict = {
            "file": vshb_path.stem.replace("_result", ""),
            "category": category,
            "reference": reference,
            "samples": offline_metrics.get("samples", 0),
        }
        if has_ref:
            _add_metric_columns(row, offline_metrics, "(offline)")
            _add_metric_columns(row, online_metrics, "(online)")
        else:
            row["samples"] = online_metrics.get("samples", 0)
            _add_metric_columns(row, online_metrics, "(online_vs_offline)")

        file_rows.append(row)

    if not file_rows:
        return None

    # 按分类分组计算加权平均
    category_data: Dict[str, List[Dict]] = {}
    for row in file_rows:
        category_data.setdefault(row["category"], []).append(row)

    metric_cols = sorted(
        {
            col
            for row in file_rows
            for col in row
            if col not in ("file", "category", "reference", "samples")
        }
    )
    summary_rows: List[Dict] = []

    total_samples = 0
    total_weighted: Dict[str, float] = {col: 0.0 for col in metric_cols}
    total_metric_samples: Dict[str, int] = {col: 0 for col in metric_cols}

    for category, entries in sorted(category_data.items()):
        cat_samples = sum(e["samples"] for e in entries)
        total_samples += cat_samples
        cat_row: Dict = {
            "file": f"{category}(avg)",
            "category": category,
            "reference": "",
            "samples": cat_samples,
        }
        for col in metric_cols:
            col_entries = [e for e in entries if col in e]
            col_samples = sum(e["samples"] for e in col_entries)
            weighted = sum(e[col] * e["samples"] for e in col_entries)
            total_weighted[col] += weighted
            total_metric_samples[col] += col_samples
            cat_row[col] = round(weighted / col_samples, 2) if col_samples > 0 else 0.0
        summary_rows.append(cat_row)

    total_row: Dict = {
        "file": "TOTAL",
        "category": "",
        "reference": "",
        "samples": total_samples,
    }
    for col in metric_cols:
        samples = total_metric_samples[col]
        total_row[col] = round(total_weighted[col] / samples, 2) if samples > 0 else 0.0
    summary_rows.append(total_row)

    all_rows = file_rows + summary_rows
    return pd.DataFrame(all_rows)
