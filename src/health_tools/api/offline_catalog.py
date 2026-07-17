"""稳定的离线算法资源发现 API。"""

from typing import List, Mapping, Optional

from health_tools.api.errors import OperationError, RequestValidationError
from health_tools.api.models import OfflineCatalogRequest, OfflineCatalogResult, OfflineVersionInfo

_EXE_NAME = "TEE_Algorithm.exe"


def _get_offline_config():
    from health_tools.core.offline import get_offline_config

    return get_offline_config()


def _is_default(
    version: str, category: Optional[str], default: object, default_category: object
) -> bool:
    if version != default:
        return False
    return default_category in (None, "") or category == default_category


def run_offline_catalog(request: OfflineCatalogRequest) -> OfflineCatalogResult:
    """返回配置中的离线算法版本及其 EXE 当前可用性。"""
    if request.chip_name is not None and not request.chip_name.strip():
        raise RequestValidationError("chip_name 不能为空")

    config = _get_offline_config()
    if not isinstance(config.versions, Mapping):
        raise OperationError("离线版本配置必须是映射")

    result: List[OfflineVersionInfo] = []
    for chip_name in sorted(config.versions, key=str.casefold):
        if request.chip_name is not None and chip_name != request.chip_name:
            continue
        chip_info = config.versions[chip_name]
        if not isinstance(chip_info, Mapping):
            raise OperationError(f"芯片 {chip_name} 的离线版本配置必须是映射")
        versions = chip_info.get("versions", {})
        default = chip_info.get("default")
        default_category = chip_info.get("default_category")

        if isinstance(versions, Mapping):
            for category in sorted(versions, key=str.casefold):
                entries = versions[category]
                if not isinstance(entries, (list, tuple)):
                    raise OperationError(f"离线版本列表格式无效: {chip_name}/{category}")
                for version in sorted((str(value) for value in entries), key=str.casefold):
                    executable = config.tools_path / chip_name / category / version / _EXE_NAME
                    result.append(
                        OfflineVersionInfo(
                            chip_name,
                            str(category),
                            version,
                            _is_default(version, str(category), default, default_category),
                            executable.is_file(),
                        )
                    )
        elif isinstance(versions, (list, tuple)):
            for version in sorted((str(value) for value in versions), key=str.casefold):
                executable = config.tools_path / chip_name / "exclusive" / version / _EXE_NAME
                result.append(
                    OfflineVersionInfo(
                        chip_name,
                        None,
                        version,
                        _is_default(version, None, default, default_category),
                        executable.is_file(),
                    )
                )
        else:
            raise OperationError(f"芯片 {chip_name} 的 versions 必须是映射或列表")

    return OfflineCatalogResult(tuple(result))
