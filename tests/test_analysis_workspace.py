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


def test_workspace_rejects_reuse_when_artifact_metadata_changes(tmp_path: Path):
    workspace = AnalysisWorkspace.create(tmp_path, {"input": "data"})
    artifact = tmp_path / "stages" / "raw" / "records.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("old", encoding="utf-8")

    workspace.start("raw", "raw-v1")
    workspace.complete("raw", [artifact])

    loaded = AnalysisWorkspace.load(tmp_path)
    assert loaded.can_reuse("raw", {"input": "data"}, fingerprint="raw-v1")

    artifact.write_text("new content", encoding="utf-8")

    loaded = AnalysisWorkspace.load(tmp_path)
    assert not loaded.can_reuse("raw", {"input": "data"}, fingerprint="raw-v1")


def test_workspace_rejects_reuse_when_current_artifact_list_changes(tmp_path: Path):
    workspace = AnalysisWorkspace.create(tmp_path, {"input": "data"})
    first = tmp_path / "a.csv"
    second = tmp_path / "b.csv"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")

    workspace.start("discover", "discover-v1")
    workspace.complete("discover", [first])

    loaded = AnalysisWorkspace.load(tmp_path)
    assert loaded.can_reuse(
        "discover",
        {"input": "data"},
        fingerprint="discover-v1",
        artifacts=[first],
    )
    assert not loaded.can_reuse(
        "discover",
        {"input": "data"},
        fingerprint="discover-v1",
        artifacts=[first, second],
    )


def test_workspace_rejects_reuse_when_stage_fingerprint_changes(tmp_path: Path):
    workspace = AnalysisWorkspace.create(tmp_path, {"input": "data"})
    artifact = tmp_path / "stages" / "plot" / "figure.png"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"png")

    workspace.start("plot", "plot-v1")
    workspace.complete("plot", [artifact])

    loaded = AnalysisWorkspace.load(tmp_path)
    assert loaded.can_reuse("plot", {"input": "data"}, fingerprint="plot-v1")
    assert not loaded.can_reuse("plot", {"input": "data"}, fingerprint="plot-v2")


def test_workspace_invalidate_from_clears_stage_and_downstream(tmp_path: Path):
    workspace = AnalysisWorkspace.create(tmp_path, {"input": "data"})
    for stage in ("discover", "check", "raw", "evaluate", "offline", "plot", "diagnose"):
        workspace.start(stage, f"{stage}-v1")
        workspace.complete(stage)

    workspace.invalidate_from("evaluate")

    loaded = AnalysisWorkspace.load(tmp_path)
    assert loaded.state.stages["discover"].status == "completed"
    assert loaded.state.stages["check"].status == "completed"
    assert loaded.state.stages["raw"].status == "completed"
    for stage in ("evaluate", "offline", "plot", "diagnose", "report"):
        assert loaded.state.stages[stage].status == "pending"
