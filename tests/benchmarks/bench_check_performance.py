"""可重复运行的 check 批量性能基准。

默认覆盖计划中的 100/500/1000 个文件和 1/2/4/8 个线程。脚本仅输出观测值，
不包含依赖机器性能的通过/失败阈值。
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import tempfile
import threading
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Sequence

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from health_tools.api import (  # noqa: E402
    CheckRequest,
    check_operation,  # noqa: E402
    run_check,
)
from health_tools.core import check_sampling  # noqa: E402
from health_tools.core.checker import DataChecker  # noqa: E402
from health_tools.utils.csv_handler import CSVHandler  # noqa: E402

DEFAULT_FILE_COUNTS = (100, 500, 1000)
DEFAULT_WORKERS = (1, 2, 4, 8)
ROWS_PER_FILE = 100


class CallCounters:
    """线程安全的基准调用计数器。"""

    def __init__(self) -> None:
        self._values: Counter[str] = Counter()
        self._lock = threading.Lock()

    def increment(self, name: str) -> None:
        with self._lock:
            self._values[name] += 1

    def get(self, name: str) -> int:
        with self._lock:
            return self._values[name]


def _parse_positive_ints(value: str) -> tuple[int, ...]:
    try:
        values = tuple(int(part.strip()) for part in value.split(",") if part.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("必须是逗号分隔的正整数") from exc
    if not values or any(item < 1 for item in values):
        raise argparse.ArgumentTypeError("必须是逗号分隔的正整数")
    return values


def _synthetic_csv_text(file_index: int) -> str:
    columns = (
        "TimeStamp",
        "FRAME_ID",
        "ACCX",
        "ACCY",
        "ACCZ",
        "REF_RESULT0",
        "REF_RESULT5",
        "ALGO_RESULT0",
        "COMP",
    )
    rows = ["Version: GH3036", ",".join(columns)]
    for row in range(ROWS_PER_FILE):
        phase = (row + file_index) % 17
        rows.append(
            ",".join(
                str(value)
                for value in (
                    row * 40,
                    row % 256,
                    100 + phase,
                    -50 + phase * 2,
                    900 - phase,
                    60 + row % 5,
                    96 + row % 3,
                    61 + row % 5,
                    60 + row % 5,
                )
            )
        )
    return "\n".join(rows) + "\n"


def generate_dataset(directory: Path, count: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        (directory / f"sample-{index:04d}.csv").write_text(
            _synthetic_csv_text(index), encoding="utf-8"
        )


def _peak_rss_mib() -> float | None:
    try:
        import psutil

        process = psutil.Process()
        memory = process.memory_info()
        peak = getattr(memory, "peak_wset", None)
        if peak is not None:
            return float(peak) / (1024 * 1024)
    except ImportError:
        pass

    if os.name == "nt":

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        handle = ctypes.windll.kernel32.GetCurrentProcess()  # type: ignore[attr-defined]
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(  # type: ignore[attr-defined]
            handle, ctypes.byref(counters), counters.cb
        )
        return counters.PeakWorkingSetSize / (1024 * 1024) if ok else None
    try:
        import resource
    except ImportError:
        return None
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return float(rss) / divisor


@contextmanager
def instrument_check(counters: CallCounters) -> Iterator[None]:
    originals: list[tuple[object, str, object]] = []

    def patch(owner: object, name: str, replacement: object) -> None:
        originals.append((owner, name, getattr(owner, name)))
        setattr(owner, name, replacement)

    def counted(name: str, function: Callable):
        def wrapper(*args, **kwargs):
            counters.increment(name)
            return function(*args, **kwargs)

        return wrapper

    original_read = CSVHandler.read
    original_timestamp = DataChecker._parse_timestamp_intervals_ms
    original_positions = check_sampling.build_sample_positions
    original_sampling = check_sampling.sample_check_seconds
    original_numeric = check_operation._FileCheckContext.numeric

    def numeric_wrapper(context, columns):
        if columns and all(str(column).upper().startswith("ACC") for column in columns):
            counters.increment("acc_preparations")
        return original_numeric(context, columns)

    patch(CSVHandler, "read", counted("csv_reads", original_read))
    patch(
        DataChecker,
        "_parse_timestamp_intervals_ms",
        staticmethod(counted("timestamp_parses", original_timestamp)),
    )
    patch(
        check_sampling,
        "build_sample_positions",
        counted("sample_positions", original_positions),
    )
    patch(check_sampling, "sample_check_seconds", counted("second_samples", original_sampling))
    patch(check_operation._FileCheckContext, "numeric", numeric_wrapper)
    try:
        yield
    finally:
        for owner, name, original in reversed(originals):
            setattr(owner, name, original)


def run_case(
    input_path: Path, report_path: Path, workers: int
) -> tuple[float, float | None, CallCounters]:
    counters = CallCounters()
    started = time.perf_counter()
    with instrument_check(counters):
        result = run_check(
            CheckRequest(
                input_path=input_path,
                chip_name="gh3036",
                checks="frame,acc,ref",
                timestamp_column="TimeStamp",
                ref_hr_column="REF_RESULT0",
                ref_spo2_column="REF_RESULT5",
                accuracy_enabled=True,
                accuracy_ref_column="REF_RESULT0",
                accuracy_online_column="ALGO_RESULT0",
                accuracy_comp_column="COMP",
                output_path=report_path,
                workers=workers,
            )
        )
    elapsed = time.perf_counter() - started
    if result.batch.fail_count or result.batch.skip_count:
        raise RuntimeError(
            f"基准输入处理失败: fail={result.batch.fail_count}, skip={result.batch.skip_count}"
        )
    return elapsed, _peak_rss_mib(), counters


def _format_rss(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def benchmark(file_counts: Sequence[int], workers: Sequence[int]) -> None:
    with tempfile.TemporaryDirectory(prefix="ghealth-check-benchmark-") as temporary:
        root = Path(temporary)
        all_data = root / "all-data"
        generate_dataset(all_data, max(file_counts))
        print(
            "files workers elapsed_s peak_rss_mib csv_reads timestamp_parses "
            "sample_positions second_samples acc_preparations"
        )
        for file_count in file_counts:
            input_path = root / f"input-{file_count}"
            input_path.mkdir()
            for source in sorted(all_data.glob("*.csv"))[:file_count]:
                os.link(source, input_path / source.name)
            for worker_count in workers:
                report_path = root / f"report-{file_count}-{worker_count}.csv"
                elapsed, peak_rss, counters = run_case(input_path, report_path, worker_count)
                print(
                    f"{file_count} {worker_count} {elapsed:.3f} {_format_rss(peak_rss)} "
                    f"{counters.get('csv_reads')} {counters.get('timestamp_parses')} "
                    f"{counters.get('sample_positions')} {counters.get('second_samples')} "
                    f"{counters.get('acc_preparations')}"
                )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--files",
        type=_parse_positive_ints,
        default=DEFAULT_FILE_COUNTS,
        help="文件规模，逗号分隔（默认: 100,500,1000）",
    )
    parser.add_argument(
        "--workers",
        type=_parse_positive_ints,
        default=DEFAULT_WORKERS,
        help="线程数组合，逗号分隔（默认: 1,2,4,8）",
    )
    args = parser.parse_args()
    benchmark(args.files, args.workers)


if __name__ == "__main__":
    main()
