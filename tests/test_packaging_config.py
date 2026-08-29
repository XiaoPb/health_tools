from pathlib import Path

SPEC = Path(__file__).parents[1] / "ghealth_tools.spec"


def test_pyinstaller_spec_declares_standalone_cli_and_runtime_assets():
    content = SPEC.read_text(encoding="utf-8")

    assert "src" in content
    assert "health_tools" in content
    assert "__main__.py" in content
    assert '"rules/**/*.yaml"' in content
    assert '"rules/**/*.yml"' in content
    assert '"templates/*.pptx"' in content
    assert '"PyQt5"' in content
    assert '"PySide6"' in content
    assert "EXE(" in content
    assert "console=True" in content
    assert "ghealth-tools-windows-x64" in content
