"""Deliberately invalid images for mock Final integration verification only."""
import os
import sys
import time
from pathlib import Path

mode = os.environ["MOCK_FAILURE"]
output = Path("/output")
if mode == "crash":
    (output / "partial.txt").write_text("partial output must not hide the crash")
    sys.exit(17)
if mode == "timeout":
    time.sleep(60)
elif mode == "oversized":
    with (output / "oversized.bin").open("wb") as stream:
        # Real allocated bytes, not just a sparse-file test.
        for _ in range(64):
            stream.write(b"x" * 1024**2)
        stream.write(b"x")
elif mode == "schema":
    (output / "forecast.parquet").write_text("not parquet")
    (output / "forecast_meta.json").write_text("{}")
    (output / "forecast_rationale.md").write_text("Fixture with deliberately invalid schema.")
else:
    raise ValueError(mode)
