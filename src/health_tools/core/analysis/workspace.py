"""分析任务阶段状态与断点恢复。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Union

STAGES = (
    "discover",
    "check",
    "classify",
    "raw",
    "evaluate",
    "offline",
    "plot",
    "diagnose",
    "report",
)
STATE_FILE = "analysis_state.json"


def request_fingerprint(request: Mapping[str, object]) -> str:
    payload = json.dumps(request, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass
class StageArtifact:
    path: str
    size: int = -1
    mtime_ns: int = -1

    @classmethod
    def from_path(cls, path: Path) -> "StageArtifact":
        stat = path.stat() if path.exists() else None
        return cls(
            str(path),
            stat.st_size if stat is not None else -1,
            stat.st_mtime_ns if stat is not None else -1,
        )

    def matches(self) -> bool:
        path = Path(self.path)
        if not path.exists():
            return False
        stat = path.stat()
        return stat.st_size == self.size and stat.st_mtime_ns == self.mtime_ns


@dataclass
class StageState:
    status: str = "pending"
    artifacts: List[StageArtifact] = field(default_factory=list)
    error: str = ""
    fingerprint: str = ""

    def __post_init__(self) -> None:
        normalized: List[StageArtifact] = []
        for value in self.artifacts:
            if isinstance(value, StageArtifact):
                normalized.append(value)
            elif isinstance(value, Mapping):
                normalized.append(StageArtifact(**value))
            else:
                path = Path(str(value))
                normalized.append(StageArtifact.from_path(path))
        self.artifacts = normalized


@dataclass
class AnalysisState:
    schema_version: int = 1
    request_fingerprint: str = ""
    inputs: List[Dict[str, object]] = field(default_factory=list)
    stages: Dict[str, StageState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.stages = {
            stage: value if isinstance(value, StageState) else StageState(**value)
            for stage, value in self.stages.items()
        }
        for stage in STAGES:
            self.stages.setdefault(stage, StageState())


class AnalysisWorkspace:
    """状态文件的原子读写及阶段产物有效性判断。"""

    def __init__(self, root: Path, state: AnalysisState) -> None:
        self.root = Path(root)
        self.state = state

    @classmethod
    def create(cls, root: Path, request: Mapping[str, object]) -> "AnalysisWorkspace":
        state = AnalysisState(request_fingerprint=request_fingerprint(request))
        workspace = cls(root, state)
        workspace.save()
        return workspace

    @classmethod
    def load(cls, root: Path) -> "AnalysisWorkspace":
        path = Path(root) / STATE_FILE
        if not path.exists():
            raise FileNotFoundError(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        state = AnalysisState(**data)
        changed = False
        for stage in state.stages.values():
            if stage.status == "running":
                stage.status = "failed"
                stage.error = stage.error or "任务中断"
                changed = True
        workspace = cls(root, state)
        if changed:
            workspace.save()
        return workspace

    def save(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / STATE_FILE
        temporary = target.with_suffix(target.suffix + ".tmp")
        payload = asdict(self.state)
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)
        return target

    def start(self, stage: str, fingerprint: str = "") -> None:
        value = self._stage(stage)
        value.status = "running"
        value.error = ""
        value.fingerprint = fingerprint
        self.save()

    def complete(
        self,
        stage: str,
        artifacts: Iterable[Union[Path, str]] = (),
        fingerprint: Optional[str] = None,
    ) -> None:
        value = self._stage(stage)
        value.status = "completed"
        if fingerprint is not None:
            value.fingerprint = fingerprint
        value.artifacts = [StageArtifact.from_path(Path(path)) for path in artifacts]
        value.error = ""
        self.save()

    def fail(self, stage: str, error: object) -> None:
        value = self._stage(stage)
        value.status = "failed"
        value.error = str(error)
        self.save()

    def can_reuse(
        self,
        stage: str,
        request: Optional[Mapping[str, object]] = None,
        fingerprint: Optional[str] = None,
        artifacts: Optional[Iterable[Union[Path, str]]] = None,
    ) -> bool:
        value = self._stage(stage)
        if value.status != "completed":
            return False
        if request is not None and self.state.request_fingerprint != request_fingerprint(request):
            return False
        if fingerprint is not None and value.fingerprint != fingerprint:
            return False
        if artifacts is not None:
            current = [StageArtifact.from_path(Path(path)) for path in artifacts]
            if len(current) != len(value.artifacts):
                return False
            if sorted((item.path, item.size, item.mtime_ns) for item in current) != sorted(
                (item.path, item.size, item.mtime_ns) for item in value.artifacts
            ):
                return False
        return all(item.matches() for item in value.artifacts)

    def invalidate_from(self, stage: str) -> None:
        try:
            index = STAGES.index(stage)
        except ValueError:
            raise ValueError(f"未知分析阶段: {stage}")
        for name in STAGES[index:]:
            self.state.stages[name] = StageState()
        self.save()

    def _stage(self, stage: str) -> StageState:
        if stage not in STAGES:
            raise ValueError(f"未知分析阶段: {stage}")
        return self.state.stages[stage]
