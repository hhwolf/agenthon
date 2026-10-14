"""The common interface for numeric and future text-aware forecasters."""

from pathlib import Path
from typing import Protocol

import pandas as pd


class Forecaster(Protocol):
    def __call__(
        self, card: dict, panels: dict[str, pd.DataFrame], text_dir: Path | None,
        asof: str, n_draws: int, seed: int | None,
    ) -> pd.DataFrame: ...
