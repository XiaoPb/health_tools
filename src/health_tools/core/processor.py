"""批量处理模块"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from health_tools.models.rules import ChipRule
from health_tools.core.splitter import DataSplitter
from health_tools.utils.csv_handler import CSVHandler
from health_tools.utils.parallel import parallel_process


class BatchProcessor:
    """批量处理器"""

    def __init__(self, chip_rule: Optional[ChipRule] = None):
        self.chip_rule = chip_rule
        self.csv_handler = CSVHandler(chip_rule)
        self.splitter = DataSplitter(chip_rule)

    def process_file(
        self,
        input_file: Path,
        output_file: Path,
        operations: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        处理单个文件

        Args:
            input_file: 输入文件
            output_file: 输出文件
            operations: 操作列表

        Returns:
            处理结果
        """
        result = {
            "input": str(input_file),
            "output": str(output_file),
            "success": False,
            "rows": 0,
            "error": None,
        }

        try:
            info, df = self.csv_handler.read(input_file)

            if df.empty:
                result["error"] = "Empty file"
                return result

            if operations:
                for op in operations:
                    op_type = op.get("type")

                    if op_type == "filter":
                        column = op.get("column")
                        condition = op.get("condition")
                        if column and condition:
                            df = self._apply_filter(df, column, condition)

                    elif op_type == "select":
                        columns = op.get("columns", [])
                        if columns:
                            existing = [c for c in columns if c in df.columns]
                            if existing:
                                df = df[existing]

                    elif op_type == "rename":
                        mapping = op.get("mapping", {})
                        df = df.rename(columns=mapping)

                    elif op_type == "dropna":
                        subset = op.get("subset")
                        df = df.dropna(subset=subset)

                    elif op_type == "fillna":
                        value = op.get("value", 0)
                        df = df.fillna(value)

            self.csv_handler.write(output_file, df, info)

            result["success"] = True
            result["rows"] = len(df)

        except Exception as e:
            result["error"] = str(e)

        return result

    def _apply_filter(
        self,
        df: pd.DataFrame,
        column: str,
        condition: str,
    ) -> pd.DataFrame:
        """应用过滤条件"""
        try:
            if column not in df.columns:
                return df

            df_col = pd.to_numeric(df[column], errors="coerce")

            if condition.startswith(">="):
                value = float(condition[2:])
                mask = df_col >= value
            elif condition.startswith("<="):
                value = float(condition[2:])
                mask = df_col <= value
            elif condition.startswith(">"):
                value = float(condition[1:])
                mask = df_col > value
            elif condition.startswith("<"):
                value = float(condition[1:])
                mask = df_col < value
            elif condition.startswith("=="):
                value = float(condition[2:])
                mask = df_col == value
            elif condition.startswith("!="):
                value = float(condition[2:])
                mask = df_col != value
            else:
                return df

            return df[mask].reset_index(drop=True)
        except Exception:
            return df

    def process_directory(
        self,
        input_dir: Union[str, Path],
        output_dir: Union[str, Path],
        operations: Optional[List[Dict[str, Any]]] = None,
        pattern: str = "*.csv",
        recursive: bool = True,
        max_workers: int = 4,
        frame_split: bool = False,
        frame_column: str = "FRAME_ID",
        verbose: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        批量处理目录

        Args:
            input_dir: 输入目录
            output_dir: 输出目录
            operations: 操作列表
            pattern: 文件匹配模式
            recursive: 是否递归
            max_workers: 最大线程数
            frame_split: 是否按帧分割
            frame_column: 帧ID列名
            verbose: 详细输出

        Returns:
            处理结果列表
        """
        input_dir = Path(input_dir)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if recursive:
            files = list(input_dir.rglob(pattern))
        else:
            files = list(input_dir.glob(pattern))

        if not files:
            return []

        def process_single(file: Path) -> Dict[str, Any]:
            if frame_split:
                file_output_dir = output_dir / file.stem
                split_files = self.splitter.split_file(
                    file,
                    file_output_dir,
                    by_column=frame_column,
                    column_value=0,
                    verbose=verbose,
                )

                results = []
                for split_file in split_files:
                    results.append(
                        {
                            "input": str(file),
                            "output": str(split_file),
                            "success": True,
                            "rows": 0,
                        }
                    )
                return {"success": True, "split_count": len(split_files)}
            else:
                relative_path = file.relative_to(input_dir)
                output_file = output_dir / relative_path
                output_file.parent.mkdir(parents=True, exist_ok=True)

                return self.process_file(file, output_file, operations)

        results = parallel_process(
            process_single,
            files,
            max_workers=max_workers,
            desc="处理文件",
            show_progress=True,
        )

        return results


def process_files(
    input_dir: Union[str, Path],
    output_dir: Union[str, Path],
    chip_rule: Optional[ChipRule] = None,
    **kwargs,
) -> List[Dict[str, Any]]:
    """
    便捷函数：批量处理文件

    Args:
        input_dir: 输入目录
        output_dir: 输出目录
        chip_rule: 芯片规则
        **kwargs: 其他参数

    Returns:
        处理结果列表
    """
    processor = BatchProcessor(chip_rule)
    return processor.process_directory(input_dir, output_dir, **kwargs)
