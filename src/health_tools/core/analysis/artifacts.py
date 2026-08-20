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
        target = Path(normalized)
        name_matches = [
            item for item in self.items.values() if Path(item.relative_path).name == target.name
        ]
        if len(name_matches) == 1:
            return name_matches[0]
        if len(name_matches) > 1:
            raise ArtifactAmbiguityError(f"文件名匹配存在歧义: {relative_path}")
        stem_matches = [
            item for item in self.items.values() if Path(item.relative_path).stem == target.stem
        ]
        if len(stem_matches) == 1:
            return stem_matches[0]
        if len(stem_matches) > 1:
            raise ArtifactAmbiguityError(f"stem 匹配存在歧义: {relative_path}")
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
    scoped_figures = _figures_in_relative_dir(relative, figures, roots)
    fallback_figures = scoped_figures if Path(rel).parent.as_posix() != "." else list(figures)
    if not candidates:
        candidates = [
            figure for figure in fallback_figures if figure.name == f"{csv_file.stem}.png"
        ]
        if len(candidates) > 1:
            raise ArtifactAmbiguityError(f"图片文件名匹配存在歧义: {csv_file}")
    if not candidates:
        by_stem = [
            figure
            for figure in fallback_figures
            if figure.stem == csv_file.stem or figure.stem.startswith(f"{csv_file.stem}_")
        ]
        exact = [figure for figure in by_stem if figure.stem == csv_file.stem]
        if len(exact) > 1:
            raise ArtifactAmbiguityError(f"图片匹配存在歧义: {csv_file}")
        if by_stem:
            candidates = by_stem
    return tuple(sorted(candidates, key=lambda path: (_figure_rank(path), path.as_posix().lower())))


def _figures_in_relative_dir(
    relative: str, figures: Sequence[Path], roots: Sequence[Path]
) -> List[Path]:
    parent = Path(relative.replace("\\", "/")).parent.as_posix()
    if parent == ".":
        parent = ""
    scoped: List[Path] = []
    for figure in figures:
        for root in roots:
            if not root.is_dir():
                continue
            try:
                candidate = figure.relative_to(root)
            except ValueError:
                continue
            if candidate.parent.as_posix() == parent:
                scoped.append(figure)
                break
    return scoped


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
    result: List[_ReportCsvEntry] = []
    usable = [path for path in available if _casefold_resolve(path) != _casefold_resolve(report)]
    root = _common_root(usable[0], usable) if usable else report.parent
    by_relative = {_relative(path, root): path for path in usable}
    by_unique_name = _unique_by(lambda path: path.name, usable)
    by_name = _group_by(lambda path: path.name, usable)
    by_unique_stem = _unique_by(lambda path: path.stem, usable)
    by_stem = _group_by(lambda path: path.stem, usable)
    for _, row in frame.iterrows():
        value = _first_non_empty(row.get(column) for column in columns)
        if value is None:
            continue
        relative_path = value.replace("\\", "/")
        candidate = Path(value)
        if candidate.is_absolute():
            csv_path = candidate
        elif not candidate.is_absolute() and (report.parent / candidate).is_file():
            csv_path = report.parent / candidate
        elif relative_path in by_relative:
            csv_path = by_relative[relative_path]
        elif candidate.name in by_name and candidate.name not in by_unique_name:
            raise ArtifactAmbiguityError(f"CSV 文件名匹配存在歧义: {value}")
        elif candidate.name in by_unique_name:
            csv_path = by_unique_name[candidate.name]
        elif candidate.stem in by_stem and candidate.stem not in by_unique_stem:
            raise ArtifactAmbiguityError(f"CSV stem 匹配存在歧义: {value}")
        elif candidate.stem in by_unique_stem:
            csv_path = by_unique_stem[candidate.stem]
        elif candidate.is_file():
            csv_path = candidate
        else:
            csv_path = candidate if candidate.is_absolute() else report.parent / candidate
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
    grouped = _group_by(key_func, paths)
    return {key: values[0] for key, values in grouped.items() if len(values) == 1}


def _group_by(key_func: Callable[[Path], str], paths: Sequence[Path]) -> Dict[str, List[Path]]:
    grouped: Dict[str, List[Path]] = {}
    for path in paths:
        grouped.setdefault(key_func(path), []).append(path)
    return grouped


def _first_non_empty(values: Iterable[object]) -> Optional[str]:
    for value in values:
        text = "" if value is None else str(value).strip()
        if text and text.lower() != "nan":
            return text
    return None


def _casefold_resolve(path: Path) -> str:
    try:
        return str(path.resolve()).casefold()
    except OSError:
        return str(path).casefold()
