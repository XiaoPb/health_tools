# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Development

```bash
pip install -e ".[dev]"       # Install with dev dependencies
health_tool --help            # Run the CLI
```

## Testing & Quality

```bash
pytest                              # Run all tests
pytest --cov=health_tools           # With coverage
pytest tests/test_foo.py            # Single test file
pytest tests/test_foo.py::test_bar  # Single test function

black src/                          # Format code
black --check src/                  # Check formatting
ruff check src/                     # Lint
mypy src/                           # Type check
```

Line length is 100 (configured in pyproject.toml for both black and ruff). Python 3.9+.

## Git Workflow

**IMPORTANT**: After any code changes, always commit with a descriptive message:

```bash
git add <files>
git commit -m "feat: description" -m "Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

Commit message format:
- `feat:` — new feature
- `fix:` — bug fix
- `refactor:` — code restructuring
- `docs:` — documentation changes
- `test:` — test additions/changes
- `chore:` — maintenance tasks

Always include the Co-Authored-By line. Never skip committing changes.

## Architecture

CLI tool for PPG (photoplethysmography) sensor data: parsing logs, plotting, classifying, converting, and splitting CSV files. Entry point: `health_tool` -> `src/health_tools/cli.py` (Click group).

### Layers

Dependency direction: `models/ <- utils/ <- rules/ <- core/ <- commands/`

- `src/health_tools/models/` — Rule dataclasses (ChipRule, ParseRule, ConvertRule, ClassifyRule). No external dependencies except utils/columns.py.
- `src/health_tools/utils/` — CSV handling, column expansion, file utilities, parallel processing, logging, accuracy helpers.
- `src/health_tools/rules/` — `RuleLoader` resolves YAML rule files (checks built-in paths under `rules/` first, then absolute/relative). `RuleValidator` validates rule schemas.
- `src/health_tools/core/` — Business logic. `LogParser`, `DataPlotter`, `DataClassifier`, `DataConverter`, `DataSplitter`, `BatchProcessor`, `STFTPlotter`. These are the classes that do the actual work.
- `src/health_tools/commands/` — Click command definitions. Each file exposes a `*_cmd` function registered in `cli.py`. Commands have short aliases (e.g., `p` for `parse`, `cv` for `convert`).

### Rule System

YAML rule files in `rules/` define behavior for each command:
- `rules/chip/` — CSV column definitions per sensor chip (gh3220, gh3036)
- `rules/parse/` — Regex patterns for log-to-CSV parsing
- `rules/classify/` — Filename-based classification rules
- `rules/convert/` — Column mapping for format conversion

Column expansion syntax:
- `ch[0-15]` expands to `ch0, ch1, ..., ch15` (chip/parse rules)
- `ch{0-15}` expands to `ch0, ch1, ..., ch15` (convert rules, `[]` preserved as literal)

### Key Dependencies

click (CLI), pandas/numpy (data), matplotlib/scipy (plotting/signal processing), pyyaml (rules), rich (terminal output), chardet (encoding detection).

## Language

This project uses Chinese for user-facing strings, comments, and documentation. Maintain this convention.
