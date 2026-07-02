from rich.console import Console

from health_tools.utils.errors import REASON_EMPTY_FILE, REASON_RULE_MISMATCH
from health_tools.utils.reporting import ResultCollector, print_summary


def test_result_collector_counts_statuses():
    collector = ResultCollector()
    collector.add_ok("ok.csv")
    collector.add_skip("skip.csv", REASON_RULE_MISMATCH)
    collector.add_fail("fail.csv", REASON_EMPTY_FILE, detail="No columns")

    assert collector.count("OK") == 1
    assert collector.count("SKIP") == 1
    assert collector.count("FAIL") == 1


def test_result_collector_groups_reasons():
    collector = ResultCollector()
    collector.add_skip("a.csv", REASON_RULE_MISMATCH)
    collector.add_skip("b.csv", REASON_RULE_MISMATCH)
    collector.add_fail("c.csv", REASON_EMPTY_FILE)

    assert collector.by_reason()[REASON_RULE_MISMATCH] == 2
    assert collector.by_reason()[REASON_EMPTY_FILE] == 1


def test_print_summary_hides_file_details_when_not_verbose(capsys):
    collector = ResultCollector()
    collector.add_ok("ok.csv")
    collector.add_fail("bad.csv", REASON_EMPTY_FILE, detail="No columns")
    console = Console(force_terminal=False, color_system=None)

    print_summary("测试结果", collector, console=console, verbose=False)

    output = capsys.readouterr().out
    assert "测试结果" in output
    assert REASON_EMPTY_FILE in output
    assert "bad.csv" not in output


def test_print_summary_shows_file_details_when_verbose(capsys):
    collector = ResultCollector()
    collector.add_fail("bad.csv", REASON_EMPTY_FILE, detail="No columns")
    console = Console(force_terminal=False, color_system=None)

    print_summary("测试结果", collector, console=console, verbose=True)

    output = capsys.readouterr().out
    assert "bad.csv" in output
    assert "No columns" in output
