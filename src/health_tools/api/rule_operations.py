"""稳定的规则目录、读取和保存 API。"""

import tempfile
import threading
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

import yaml

from health_tools.api.errors import RequestValidationError, RuleLoadError
from health_tools.api.models import (
    RuleCatalogResult,
    RuleDocumentResult,
    RuleInfo,
    RuleListRequest,
    RuleReadRequest,
    RuleSaveRequest,
    RuleSource,
    RuleType,
    RuleVariantInfo,
)
from health_tools.config import DEFAULT_RULES_DIR, load_config
from health_tools.rules.loader import RuleLoader
from health_tools.rules.validator import RuleValidator
from health_tools.utils.atomic_file import atomic_write_text, read_text_revision

_RULE_SUFFIXES = {".yaml", ".yml"}
_write_lock = threading.RLock()


def _rule_type(value: object) -> RuleType:
    try:
        return value if isinstance(value, RuleType) else RuleType(str(value))
    except ValueError as exc:
        raise RequestValidationError(f"不支持的规则类型: {value}") from exc


def _rule_source(value: object) -> RuleSource:
    try:
        return value if isinstance(value, RuleSource) else RuleSource(str(value))
    except ValueError as exc:
        raise RequestValidationError(f"不支持的规则来源: {value}") from exc


def _validate_rule_name(name: str) -> str:
    if not isinstance(name, str) or not name or name in {".", ".."}:
        raise RequestValidationError("规则名称不能为空")
    if "/" in name or "\\" in name:
        raise RequestValidationError(f"规则名称不能包含路径: {name}")
    path = Path(name)
    if path.is_absolute() or path.name != name:
        raise RequestValidationError(f"规则名称必须是单一文件名: {name}")
    if path.suffix.lower() not in _RULE_SUFFIXES:
        raise RequestValidationError("规则文件必须使用 .yaml 或 .yml 后缀")
    return name


def _user_rules_root() -> Path:
    config = load_config()
    return Path(config.get("rules_dir", str(DEFAULT_RULES_DIR))).expanduser()


def _rule_path(root: Path, rule_type: RuleType, name: str) -> Path:
    directory = (root / rule_type.value).resolve(strict=False)
    candidate = (directory / name).resolve(strict=False)
    if candidate.parent != directory:
        raise RequestValidationError(f"规则路径超出用户规则目录: {name}")
    return candidate


def _files(directory: Path) -> Iterable[Path]:
    if not directory.exists():
        return ()
    return (
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in _RULE_SUFFIXES
    )


def _variant(path: Path, source: RuleSource) -> RuleVariantInfo:
    try:
        _, revision = read_text_revision(path)
    except (OSError, UnicodeError) as exc:
        raise RuleLoadError(f"无法读取规则 {path}: {exc}") from exc
    return RuleVariantInfo(source, path, source == RuleSource.USER, revision)


def _build_rule_info(rule_type: RuleType, name: str) -> Optional[RuleInfo]:
    user_path = _rule_path(_user_rules_root(), rule_type, name)
    builtin_path = _rule_path(RuleLoader.get_builtin_rules_path(), rule_type, name)
    variants = []
    if user_path.is_file():
        variants.append(_variant(user_path, RuleSource.USER))
    if builtin_path.is_file():
        variants.append(_variant(builtin_path, RuleSource.BUILTIN))
    if not variants:
        return None
    effective = variants[0]
    return RuleInfo(
        rule_type=rule_type,
        name=name,
        source=effective.source,
        path=effective.path,
        writable=effective.writable,
        overrides_builtin=len(variants) == 2,
        variants=tuple(variants),
    )


def _catalog(rule_types: Iterable[RuleType]) -> Tuple[RuleInfo, ...]:
    result = []
    user_root = _user_rules_root()
    builtin_root = RuleLoader.get_builtin_rules_path()
    for rule_type in rule_types:
        names: Dict[str, str] = {}
        for root in (builtin_root, user_root):
            for path in _files(root / rule_type.value):
                names.setdefault(path.name.casefold(), path.name)
        for name in sorted(names.values(), key=str.casefold):
            info = _build_rule_info(rule_type, name)
            if info is not None:
                result.append(info)
    return tuple(result)


def run_list_rules(request: RuleListRequest) -> RuleCatalogResult:
    """列出内置和用户规则，并合并同名来源变体。"""
    rule_types = (
        (_rule_type(request.rule_type),) if request.rule_type is not None else tuple(RuleType)
    )
    return RuleCatalogResult(_catalog(rule_types))


def _select_variant(info: RuleInfo, source: RuleSource) -> RuleVariantInfo:
    if source == RuleSource.EFFECTIVE:
        source = info.source
    for variant in info.variants:
        if variant.source == source:
            return variant
    raise RuleLoadError(f"规则 {info.rule_type.value}/{info.name} 不存在 {source.value} 版本")


def run_read_rule(request: RuleReadRequest) -> RuleDocumentResult:
    """读取规则的有效、用户或内置 YAML 原文。"""
    rule_type = _rule_type(request.rule_type)
    name = _validate_rule_name(request.name)
    source = _rule_source(request.variant)
    info = _build_rule_info(rule_type, name)
    if info is None:
        raise RuleLoadError(f"规则不存在: {rule_type.value}/{name}")
    variant = _select_variant(info, source)
    try:
        document, revision = read_text_revision(variant.path)
    except (OSError, UnicodeError) as exc:
        raise RuleLoadError(f"无法读取规则 {variant.path}: {exc}") from exc
    selected_info = RuleInfo(
        rule_type=info.rule_type,
        name=info.name,
        source=variant.source,
        path=variant.path,
        writable=variant.writable,
        overrides_builtin=info.overrides_builtin,
        variants=info.variants,
    )
    return RuleDocumentResult(selected_info, document, revision)


def _validate_source(rule_type: RuleType, source: str, directory: Path) -> None:
    try:
        document = yaml.safe_load(source)
    except yaml.YAMLError as exc:
        raise RequestValidationError(f"YAML 解析失败: {exc}") from exc
    if not isinstance(document, dict):
        raise RequestValidationError("规则 YAML 根节点必须是映射")

    directory.mkdir(parents=True, exist_ok=True)
    temporary: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=directory,
            prefix=".validate.",
            suffix=".yaml",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(source)
        errors = RuleValidator.validate_file(temporary)
        if errors:
            raise RuleLoadError("规则校验失败: " + "; ".join(errors))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run_save_rule(request: RuleSaveRequest) -> RuleDocumentResult:
    """校验并保存用户规则，使用 revision 防止覆盖外部修改。"""
    rule_type = _rule_type(request.rule_type)
    name = _validate_rule_name(request.name)
    if not isinstance(request.source, str):
        raise RequestValidationError("规则 source 必须是字符串")
    user_directory = _user_rules_root() / rule_type.value
    target = _rule_path(_user_rules_root(), rule_type, name)

    with _write_lock:
        current = _build_rule_info(rule_type, name)
        if current is None:
            if request.expected_revision is not None:
                raise RequestValidationError(
                    f"规则 revision 冲突: expected={request.expected_revision}, current=None"
                )
        else:
            current_variant = _select_variant(current, RuleSource.EFFECTIVE)
            if request.expected_revision is None:
                raise RequestValidationError(
                    f"规则已存在，保存时必须提供 expected_revision: current={current_variant.revision}"
                )
            if request.expected_revision != current_variant.revision:
                raise RequestValidationError(
                    "规则 revision 冲突: "
                    f"expected={request.expected_revision}, current={current_variant.revision}"
                )

        _validate_source(rule_type, request.source, user_directory)
        atomic_write_text(target, request.source)

    return run_read_rule(RuleReadRequest(rule_type, name, RuleSource.USER))
