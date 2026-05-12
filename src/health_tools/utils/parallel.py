"""并行处理模块"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List

from tqdm import tqdm


def parallel_process(
    func: Callable,
    items: List[Any],
    max_workers: int = 4,
    desc: str = "Processing",
    show_progress: bool = True,
) -> List[Any]:
    """
    多线程并行处理（保持输入顺序）

    Args:
        func: 处理函数
        items: 待处理项列表
        max_workers: 最大线程数
        desc: 进度条描述
        show_progress: 是否显示进度条

    Returns:
        处理结果列表（与输入顺序一致）
    """
    results: List[Any] = [None] * len(items)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(func, item): i for i, item in enumerate(items)}

        if show_progress:
            futures_iter = tqdm(
                as_completed(futures),
                total=len(futures),
                desc=desc,
            )
        else:
            futures_iter = as_completed(futures)

        for future in futures_iter:
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                results[idx] = {"error": str(e), "item": str(items[idx])}

    return results


def parallel_process_with_index(
    func: Callable,
    items: List[Any],
    max_workers: int = 4,
    desc: str = "Processing",
    show_progress: bool = True,
) -> Dict[int, Any]:
    """
    多线程并行处理（保留索引）

    Args:
        func: 处理函数
        items: 待处理项列表
        max_workers: 最大线程数
        desc: 进度条描述
        show_progress: 是否显示进度条

    Returns:
        {索引: 结果} 字典
    """
    results = {}

    def wrapped_func(index, item):
        return index, func(item)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(wrapped_func, i, item): i for i, item in enumerate(items)}

        if show_progress:
            futures_iter = tqdm(
                as_completed(futures),
                total=len(futures),
                desc=desc,
            )
        else:
            futures_iter = as_completed(futures)

        for future in futures_iter:
            try:
                index, result = future.result()
                results[index] = result
            except Exception as e:
                index = futures[future]
                results[index] = {"error": str(e)}

    return results


def batch_process(
    func: Callable,
    items: List[Any],
    batch_size: int = 100,
    max_workers: int = 4,
    desc: str = "Processing",
) -> List[Any]:
    """
    批量并行处理

    Args:
        func: 处理函数
        items: 待处理项列表
        batch_size: 批次大小
        max_workers: 最大线程数
        desc: 进度条描述

    Returns:
        处理结果列表
    """
    all_results = []

    for i in tqdm(range(0, len(items), batch_size), desc=desc):
        batch = items[i : i + batch_size]
        batch_results = parallel_process(
            func,
            batch,
            max_workers=max_workers,
            show_progress=False,
        )
        all_results.extend(batch_results)

    return all_results
