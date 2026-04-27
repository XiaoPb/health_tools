from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Config:
    input_path: Optional[Path] = None
    output_path: Optional[Path] = None
    rule_file: Optional[Path] = None
    chip_name: Optional[str] = None
    verbose: bool = False
    log_level: str = "info"

    delimiter: str = ","
    encoding: str = "utf-8"
    sample_rate: Optional[int] = None
