"""GHealth Tools Streamlit UI"""

from pathlib import Path


def get_app_path() -> str:
    return str(Path(__file__).parent / "app.py")
