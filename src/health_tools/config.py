"""全局配置管理"""

from pathlib import Path
from typing import Optional

import yaml

CONFIG_DIR = Path.home() / ".ghealth_tools"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
DEFAULT_RULES_DIR = CONFIG_DIR / "rules"
RULE_SUBDIRS = ["chip", "parse", "classify", "convert"]

_config_cache: Optional[dict] = None


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
    return CONFIG_DIR
