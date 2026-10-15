import argparse
import os
from pathlib import Path

from .io import read_card, read_panels, write_forecast
from . import m0, numeric_v1, numeric_v1_1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Numeric forecast with optional evidence-based text overlay and fallback")
    parser.add_argument("--panels", type=Path, required=True)
    parser.add_argument("--text", type=Path)
    parser.add_argument("--asof", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--card", type=Path)
    parser.add_argument("--n-draws", type=int)
    parser.add_argument("--forecaster", choices=["numeric_v1_1", "numeric_v1", "text_v1", "m0"], default=os.environ.get("T2_DEFAULT_FORECASTER", "numeric_v1_1"))
    parser.add_argument("--text-mode", choices=["numeric_only", "card_notes_only", "notes_only", "labels"],
                        help="override the committed text ship decision")
    parser.add_argument("--text-lambda", type=float, choices=[0., .5, 1.])
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
        from . import text_v1
        forecast = text_v1.make_forecaster(args.text_mode, args.text_lambda)
    else:
        forecast = {"m0": m0.forecast, "numeric_v1": numeric_v1.forecast,
                    "numeric_v1_1": numeric_v1_1.forecast}[args.forecaster]
    options = ({"text_mode": args.text_mode, "text_lambda": args.text_lambda}
               if args.forecaster in ("numeric_v1", "numeric_v1_1") else {})
    options = {k: v for k, v in options.items() if v is not None}
    result = forecast(card, panels, args.text, args.asof, n_draws, args.seed, **options)
    if panel_error:
        result.attrs["rationale"] += "\n\n" + panel_error
    write_forecast(card, result, args.out)


if __name__ == "__main__":
    main()
