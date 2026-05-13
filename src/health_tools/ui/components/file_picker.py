"""文件/目录路径输入组件"""

from pathlib import Path
from typing import Optional

import streamlit as st


def file_input(label: str = "输入文件", key: str = "input_file") -> Optional[Path]:
    path_str = st.text_input(label, key=key, placeholder="输入文件路径或拖拽文件到此")
    if path_str:
        p = Path(path_str.strip().strip('"'))
        if p.exists() and p.is_file():
            return p
        elif path_str.strip():
            st.warning(f"文件不存在: {path_str}")
    return None


def dir_input(label: str = "输入目录", key: str = "input_dir") -> Optional[Path]:
    path_str = st.text_input(label, key=key, placeholder="输入目录路径")
    if path_str:
        p = Path(path_str.strip().strip('"'))
        if p.exists() and p.is_dir():
            return p
        elif path_str.strip():
            st.warning(f"目录不存在: {path_str}")
    return None


def path_input(label: str = "输入路径", key: str = "input_path") -> Optional[Path]:
    path_str = st.text_input(label, key=key, placeholder="输入文件或目录路径")
    if path_str:
        p = Path(path_str.strip().strip('"'))
        if p.exists():
            return p
        elif path_str.strip():
            st.warning(f"路径不存在: {path_str}")
    return None


def output_input(label: str = "输出路径", key: str = "output_path") -> Optional[str]:
    return st.text_input(label, key=key, placeholder="输出文件或目录路径") or None
