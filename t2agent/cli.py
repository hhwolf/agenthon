import argparse
from pathlib import Path

from .io import read_card, read_panels, write_forecast
from . import m0, numeric_v1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Text-free numeric forecast with fallback")
    parser.add_argument("--panels", type=Path, required=True)
    parser.add_argument("--text", type=Path)
    parser.add_argument("--asof", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--card", type=Path)
    parser.add_argument("--n-draws", type=int)
    parser.add_argument("--forecaster", choices=["numeric_v1", "text_v1", "m0"], default="numeric_v1")
    parser.add_argument("--seed", type=int)
    args = parser.parse_args(argv)
    path = args.card or next((p for p in (args.panels / "card.toml", args.panels.parent / "card.toml")
                              if p.exists()), None)
    if path is None:
        parser.error("card.toml not found beside panels")
    card = read_card(path)
    n_draws = args.n_draws or (500 if args.forecaster == "m0" else 2000)
    try:
        panels = read_panels(args.panels)
        panel_error = None
    except Exception as exc:
        if args.forecaster == "m0":
            raise
        panels = {}
        panel_error = f"Panel load failed: {type(exc).__name__}: {exc}"
    if args.forecaster == "text_v1":
        from . import text_v1  # imported only when selected: the numeric path never needs the text layer

        forecast = text_v1.forecast
    else:
        forecast = numeric_v1.forecast if args.forecaster == "numeric_v1" else m0.forecast
    result = forecast(card, panels, args.text, args.asof, n_draws, args.seed)
    if panel_error:
        result.attrs["rationale"] += "\n\n" + panel_error
    write_forecast(card, result, args.out)


if __name__ == "__main__":
    main()
