from pathlib import Path

from health_tools.core.analysis.workspace import AnalysisWorkspace


def test_workspace_reuses_completed_stage_when_fingerprint_matches(tmp_path: Path):
    workspace = AnalysisWorkspace.create(tmp_path, {"input": "data", "type": "hr"})
    artifact = tmp_path / "stages" / "check" / "check_report.csv"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("ok", encoding="utf-8")
    workspace.complete("check", [artifact])
    loaded = AnalysisWorkspace.load(tmp_path)
    assert loaded.can_reuse("check", {"input": "data", "type": "hr"})


def test_workspace_marks_running_stage_failed_on_load(tmp_path: Path):
    workspace = AnalysisWorkspace.create(tmp_path, {"input": "data"})
    workspace.start("offline")
    loaded = AnalysisWorkspace.load(tmp_path)
    assert loaded.state.stages["offline"].status == "failed"
