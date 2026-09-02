from io import StringIO

from rich.console import Console

from health_tools.api import BatchResult, ItemResult, ItemStatus
from health_tools.commands.api_support import print_batch


def test_print_batch_verbose_prints_each_detail_once():
    stream = StringIO()
    console = Console(file=stream, color_system=None, width=120)
    result = BatchResult(
        operation="test",
        items=(
            ItemResult(
                status=ItemStatus.FAIL,
                input="failed.csv",
                reason="处理失败",
                detail="failed-task.log",
            ),
            ItemResult(
                status=ItemStatus.WARN,
                input="warn.csv",
                reason="结果警告",
                detail="warn-task.log",
            ),
            ItemResult(
                status=ItemStatus.OK,
                input="ok.csv",
                detail="ok-detail",
            ),
        ),
    )

    print_batch("测试", result, console=console, verbose=True)

    output = stream.getvalue()
    assert output.count("failed-task.log") == 1
    assert output.count("warn-task.log") == 1
    assert output.count("ok-detail") == 1
