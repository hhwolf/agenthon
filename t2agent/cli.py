import argparse
from pathlib import Path

from .io import read_card, read_panels, write_forecast
from .m0 import forecast


def main(argv=None):
    parser = argparse.ArgumentParser(description="M0 numeric forecast")
    parser.add_argument("--panels", type=Path, required=True)
    parser.add_argument("--text", type=Path)
    parser.add_argument("--asof", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--card", type=Path)
    parser.add_argument("--n-draws", type=int, default=500)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args(argv)
    path = args.card or next((p for p in (args.panels / "card.toml", args.panels.parent / "card.toml")
                              if p.exists()), None)
    if path is None:
        parser.error("card.toml not found beside panels")
    card = read_card(path)
    result = forecast(card, read_panels(args.panels), args.text, args.asof, args.n_draws, args.seed)
    write_forecast(card, result, args.out)


if __name__ == "__main__":
    main()
