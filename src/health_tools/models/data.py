from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd


@dataclass
class PPGData:
    df: pd.DataFrame
    metadata: Dict[str, str] = field(default_factory=dict)
    sample_rate: Optional[int] = None

    @property
    def columns(self) -> List[str]:
        return list(self.df.columns)

    @property
    def row_count(self) -> int:
        return len(self.df)

    def get_channel(self, name: str) -> Optional[pd.Series]:
        if name in self.df.columns:
            return self.df[name]
        return None

    def to_csv(self, path: str, **kwargs) -> None:
        self.df.to_csv(path, index=False, **kwargs)

    @classmethod
    def from_csv(cls, path: str, **kwargs) -> "PPGData":
        df = pd.read_csv(path, **kwargs)
        return cls(df=df)
