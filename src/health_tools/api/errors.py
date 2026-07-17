"""GHealth Tools 公共 API 异常。"""

from typing import Optional


class GHealthError(Exception):
    """公共 API 异常基类。"""


class RequestValidationError(GHealthError):
    """请求参数无效。"""


class RuleLoadError(GHealthError):
    """规则无法加载。"""


class OperationError(GHealthError):
    """任务级执行失败。"""


class CallbackError(GHealthError):
    """调用方提供的回调执行失败。"""


class OperationCancelled(GHealthError):
    """任务在安全检查点被取消。"""

    def __init__(self, stage: str, partial_result: Optional[object] = None) -> None:
        super().__init__(f"任务已取消: {stage}")
        self.stage = stage
        self.partial_result = partial_result
