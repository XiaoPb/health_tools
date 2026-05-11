"""基础导入测试，确保包结构完整。"""


def test_import_package():
    import health_tools

    assert health_tools.__version__


def test_import_cli():
    from health_tools.cli import main

    assert main is not None


def test_import_models():
    from health_tools.models.rules import ChipRule, ClassifyRule, ConvertRule, ParseRule

    assert all([ChipRule, ClassifyRule, ConvertRule, ParseRule])


def test_import_core():
    from health_tools.core import (
        DataClassifier,
        DataConverter,
        DataSplitter,
        LogParser,
    )

    assert all([DataClassifier, DataConverter, DataSplitter, LogParser])


def test_import_rules():
    from health_tools.rules.loader import RuleLoader

    assert RuleLoader is not None
