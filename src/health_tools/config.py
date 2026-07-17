"""全局配置管理"""

import shutil
import threading
from pathlib import Path
from typing import Optional

import yaml

from health_tools.utils.atomic_file import (
    atomic_write_text,
    content_revision,
    current_revision,
    read_text_revision,
)

CONFIG_DIR = Path.home() / ".ghealth_tools"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
DEFAULT_RULES_DIR = CONFIG_DIR / "rules"
RULE_SUBDIRS = ["chip", "parse", "classify", "convert", "evaluate", "analysis"]

_config_cache: Optional[dict] = None
_config_lock = threading.RLock()


class ConfigRevisionConflict(Exception):
    """配置文件 revision 与调用方预期不一致。"""

    def __init__(self, expected: Optional[str], current: Optional[str]) -> None:
        super().__init__(f"expected={expected}, current={current}")
        self.expected = expected
        self.current = current


def _get_builtin_rules_path() -> Path:
    # 包内规则目录（wheel 安装后可用）
    pkg_rules = Path(__file__).parent / "rules"
    if pkg_rules.exists() and any(pkg_rules.glob("*/*.yaml")):
        return pkg_rules
    # 开发模式：项目根目录的 rules/
    project_rules = Path(__file__).parent.parent.parent / "rules"
    if project_rules.exists():
        return project_rules
    return pkg_rules


def load_config() -> dict:
    global _config_cache
    with _config_lock:
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
    source = yaml.dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False)
    with _config_lock:
        atomic_write_text(CONFIG_FILE, source)
        _config_cache = dict(config)


def read_config_document() -> tuple[str, Optional[str]]:
    """读取配置 YAML 原文和 revision。"""
    with _config_lock:
        if not CONFIG_FILE.exists():
            return "", None
        return read_text_revision(CONFIG_FILE)


def replace_config_document(source: str, config: dict, expected_revision: Optional[str]) -> str:
    """校验当前 revision 后替换配置并刷新进程内缓存。"""
    global _config_cache
    with _config_lock:
        current = current_revision(CONFIG_FILE)
        if current is None:
            if expected_revision is not None:
                raise ConfigRevisionConflict(expected_revision, current)
        elif expected_revision is None or current != expected_revision:
            raise ConfigRevisionConflict(expected_revision, current)
        atomic_write_text(CONFIG_FILE, source)
        _config_cache = dict(config)
        return content_revision(source.encode("utf-8"))


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


def sync_builtin_rules(force: bool = False) -> int:
    """将内置规则文件同步到用户规则目录。

    force=False: 仅复制不存在的文件
    force=True: 强制覆盖所有内置规则文件
    """
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
            if force or not dst_file.exists():
                shutil.copy2(src_file, dst_file)
                count += 1
    return count
