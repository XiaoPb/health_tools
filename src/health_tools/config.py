"""全局配置管理"""

from pathlib import Path
from typing import Optional

import yaml

CONFIG_DIR = Path.home() / ".ghealth_tools"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
DEFAULT_RULES_DIR = CONFIG_DIR / "rules"
RULE_SUBDIRS = ["chip", "parse", "classify", "convert"]


def load_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


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
