"""公共 API 的进度与取消上下文。"""

from dataclasses import dataclass
from typing import Callable, Optional

from health_tools.api.errors import CallbackError, OperationCancelled
from health_tools.api.models import ProgressEvent


@dataclass(frozen=True)
class ExecutionContext:
    on_progress: Optional[Callable[[ProgressEvent], None]] = None
    is_cancelled: Optional[Callable[[], bool]] = None

    def emit(self, event: ProgressEvent) -> None:
        if self.on_progress is None:
            return
        try:
            self.on_progress(event)
        except Exception as exc:
            raise CallbackError(f"进度回调执行失败: {exc}") from exc

    def check_cancelled(self, stage: str, partial_result: Optional[object] = None) -> None:
        if self.is_cancelled is None:
            return
        try:
            cancelled = self.is_cancelled()
        except Exception as exc:
            raise CallbackError(f"取消回调执行失败: {exc}") from exc
        if cancelled:
            raise OperationCancelled(stage, partial_result)
