"""已有分析输入、报告和图片产物的确定性索引。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

MATCH_ORDER = ("relative_path", "file_name", "unique_stem")
_KINDS = ("time", "ac", "psd", "stft", "evidence")


class ArtifactAmbiguityError(ValueError):
    """多个候选产物无法确定唯一匹配。"""


@dataclass(frozen=True)
class ArtifactItem:
    csv_path: Path
    relative_path: str
    figures: Tuple[Path, ...] = ()
    status: str = "OK"
    reason: str = ""

    @property
    def primary_figure(self) -> Optional[Path]:
        return self.figures[0] if self.figures else None

    @property
    def secondary_figures(self) -> Tuple[Path, ...]:
        return self.figures[1:]


@dataclass(frozen=True)
class _ReportCsvEntry:
    relative_path: str
    csv_path: Path
    status: str = "OK"
    reason: str = ""


@dataclass
class ArtifactIndex:
    items: Dict[str, ArtifactItem] = field(default_factory=dict)
    figures: Tuple[Path, ...] = ()

    @classmethod
    def build(
        cls,
        csv_paths: Iterable[Path],
        figure_dirs: Iterable[Path] = (),
        check_report: Optional[Path] = None,
    ) -> "ArtifactIndex":
        csv_files = [Path(path) for path in csv_paths if Path(path).is_file()]
        report_entries: List[_ReportCsvEntry] = []
        if check_report is not None and Path(check_report).is_file():
            report_entries = _csvs_from_report(Path(check_report), csv_files)
            if report_entries:
                csv_files = [entry.csv_path for entry in report_entries]
        roots = [Path(path) for path in figure_dirs]
        figure_files: List[Path] = []
        for root in roots:
            if root.is_file() and root.suffix.lower() == ".png":
                figure_files.append(root)
            elif root.is_dir():
                figure_files.extend(sorted(root.rglob("*.png")))
        figure_files = sorted(set(figure_files), key=lambda path: path.as_posix().lower())
        if report_entries:
            items: Dict[str, ArtifactItem] = {}
            for entry in report_entries:
                figures = (
                    _match_figures(entry.relative_path, entry.csv_path, figure_files, roots)
                    if entry.status == "OK"
                    else ()
                )
                items[entry.relative_path] = ArtifactItem(
                    csv_path=entry.csv_path,
                    relative_path=entry.relative_path,
                    figures=figures,
                    status=entry.status,
                    reason=entry.reason,
                )
            return cls(items=items, figures=tuple(figure_files))
        figures_by_csv: Dict[str, Tuple[Path, ...]] = {}
        for csv_file in csv_files:
            root = _common_root(csv_file, csv_files)
            relative = _relative(csv_file, root)
            selected = _match_figures(relative, csv_file, figure_files, roots)
            figures_by_csv[relative] = selected
        items = {
            _relative(path, _common_root(path, csv_files)): ArtifactItem(
                csv_path=path,
                relative_path=_relative(path, _common_root(path, csv_files)),
                figures=figures_by_csv.get(_relative(path, _common_root(path, csv_files)), ()),
                status="OK" if path.exists() else "SKIP",
                reason="" if path.exists() else "文件不存在",
            )
            for path in csv_files
        }
        return cls(items=items, figures=tuple(figure_files))

    def item_for(self, relative_path: str) -> Optional[ArtifactItem]:
        normalized = relative_path.replace("\\", "/")
        if normalized in self.items:
            return self.items[normalized]
        matches = [
            item
            for item in self.items.values()
            if Path(item.csv_path).name == Path(normalized).name
        ]
        if len(matches) == 1:
            return matches[0]
        return None

    def figure_for(self, relative_path: str) -> Optional[Path]:
        item = self.item_for(relative_path)
        return item.primary_figure if item else None

    def figures_for(self, relative_path: str) -> Tuple[Path, ...]:
        item = self.item_for(relative_path)
        return item.figures if item else ()


def _common_root(path: Path, paths: Sequence[Path]) -> Path:
    if not paths:
        return path.parent
    if len(paths) == 1:
        return path.parent
    try:
        root = Path(path.anchor or path.root)
        parts = path.parts
        for index, part in enumerate(parts):
            if all(other.parts[index] == part for other in paths if len(other.parts) > index):
                root = Path(*parts[: index + 1])
            else:
                break
        return root if root != Path(path.anchor or path.root) else path.parent
    except (IndexError, ValueError):
        return path.parent


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _match_figures(
    relative: str, csv_file: Path, figures: Sequence[Path], roots: Sequence[Path]
) -> Tuple[Path, ...]:
    rel = relative.replace("\\", "/")
    rel_stem = Path(rel).with_suffix("").as_posix()
    same_relative: List[Path] = []
    for figure in figures:
        for root in roots:
            if root.is_dir():
                try:
                    candidate = figure.relative_to(root).as_posix()
                except ValueError:
                    continue
                if Path(candidate).with_suffix("").as_posix() == rel_stem:
                    same_relative.append(figure)
    candidates = same_relative
    if not candidates:
        candidates = [figure for figure in figures if figure.name == f"{csv_file.stem}.png"]
    if not candidates:
        by_stem = [
            figure
            for figure in figures
            if figure.stem == csv_file.stem or figure.stem.startswith(f"{csv_file.stem}_")
        ]
        exact = [figure for figure in by_stem if figure.stem == csv_file.stem]
        if len(exact) > 1:
            raise ArtifactAmbiguityError(f"图片匹配存在歧义: {csv_file}")
        if by_stem:
            candidates = by_stem
    return tuple(sorted(candidates, key=lambda path: (_figure_rank(path), path.as_posix().lower())))


def _figure_rank(path: Path) -> int:
    lower = path.stem.lower()
    for index, kind in enumerate(_KINDS):
        if kind in lower:
            return index
    return len(_KINDS)


def _csvs_from_report(report: Path, available: Sequence[Path]) -> List[_ReportCsvEntry]:
    try:
        import pandas as pd

        frame = pd.read_csv(report, encoding="utf-8-sig")
    except Exception:
        return []
    columns = [
        name for name in ("文件相对路径", "文件名", "file", "input") if name in frame.columns
    ]
    if not columns:
        return []
    values = [str(value) for value in frame[columns[0]].dropna().tolist()]
    result: List[_ReportCsvEntry] = []
    usable = [path for path in available if _casefold_resolve(path) != _casefold_resolve(report)]
    by_unique_name = _unique_by(lambda path: path.name, usable)
    for value in values:
        relative_path = value.replace("\\", "/")
        candidate = Path(value)
        if candidate.is_file():
            csv_path = candidate
        elif not candidate.is_absolute() and (report.parent / candidate).is_file():
            csv_path = report.parent / candidate
        elif candidate.name in by_unique_name:
            csv_path = by_unique_name[candidate.name]
        else:
            csv_path = report.parent / candidate
        if csv_path.exists():
            result.append(_ReportCsvEntry(relative_path=relative_path, csv_path=csv_path))
        else:
            result.append(
                _ReportCsvEntry(
                    relative_path=relative_path,
                    csv_path=csv_path,
                    status="SKIP",
                    reason="文件不存在",
                )
            )
    return result


def _unique_by(key_func: Callable[[Path], str], paths: Sequence[Path]) -> Dict[str, Path]:
    grouped: Dict[str, List[Path]] = {}
    for path in paths:
        grouped.setdefault(key_func(path), []).append(path)
    return {key: values[0] for key, values in grouped.items() if len(values) == 1}


def _casefold_resolve(path: Path) -> str:
    try:
        return str(path.resolve()).casefold()
    except OSError:
        return str(path).casefold()
