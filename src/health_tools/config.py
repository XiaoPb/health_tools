"""全局配置管理"""

import shutil
from pathlib import Path
from typing import Optional

import yaml

CONFIG_DIR = Path.home() / ".ghealth_tools"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
DEFAULT_RULES_DIR = CONFIG_DIR / "rules"
RULE_SUBDIRS = ["chip", "parse", "classify", "convert", "evaluate"]

_config_cache: Optional[dict] = None


def _get_builtin_rules_path() -> Path:
    candidate = Path(__file__).parent.parent.parent / "rules"
    if candidate.exists():
        return candidate
    return Path(__file__).parent / "rules"


def load_config() -> dict:
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            _config_cache = yaml.safe_load(f) or {}
    else:
        _config_cache = {}
    return _config_cache


def save_config(config: dict) -> None:
    global _config_cache
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    _config_cache = config


def get_user_rules_dir() -> Optional[Path]:
    config = load_config()
    rules_dir = Path(config.get("rules_dir", str(DEFAULT_RULES_DIR)))
    if rules_dir.exists():
        return rules_dir
    return None


def init_config_dir() -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    for subdir in RULE_SUBDIRS:
        (DEFAULT_RULES_DIR / subdir).mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        save_config({"rules_dir": str(DEFAULT_RULES_DIR)})
    sync_builtin_rules()
    return CONFIG_DIR


def sync_builtin_rules() -> int:
    """将内置规则文件同步到用户规则目录（不覆盖已存在的文件）"""
    builtin_path = _get_builtin_rules_path()
    if not builtin_path.exists():
        return 0

    count = 0
    for subdir in RULE_SUBDIRS:
        src_dir = builtin_path / subdir
        dst_dir = DEFAULT_RULES_DIR / subdir
        if not src_dir.exists():
            continue
        dst_dir.mkdir(parents=True, exist_ok=True)
        for src_file in src_dir.glob("*.yaml"):
            dst_file = dst_dir / src_file.name
            if not dst_file.exists():
                shutil.copy2(src_file, dst_file)
                count += 1
    return count
