"""Build local history unions and labelled cards. This module never ships."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import tomli_w

from t2agent.io import read_card, read_panels
from t2agent.m0 import cell_metadata, history, intervals


def units(root: Path, exemplar=False) -> list[Path]:
    return [p.parent for p in sorted(root.glob("*/card.toml"))
            if exemplar or (p.parent / "forecast_spec.json").exists()]


def fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for unit in units(root):
        paths = [unit / "card.toml", unit / "forecast_spec.json"]
        paths += sorted(unit.glob("*.parquet")) + sorted((unit / "panels").glob("*.parquet"))
        for p in paths:
            digest.update(str(p.relative_to(root)).encode())
            digest.update(p.read_bytes())
    return digest.hexdigest()


def build_union(root: Path, out: Path) -> tuple[pd.DataFrame, dict]:
    """Keep source/vintage on every donor row; latest cutoff wins union conflicts."""
    out.mkdir(parents=True, exist_ok=True)
    signature = fingerprint(root)
    cache = out / "donors.parquet"
    if cache.exists() and (out / "provenance.json").exists():
        meta = json.loads((out / "provenance.json").read_text())
        if meta["input_sha256"] == signature:
            return pd.read_parquet(cache), meta
    frames = []
    for unit in units(root):
        c = read_card(unit / "card.toml")
        for name, f in read_panels(unit / "panels").items():
            f = f.rename(columns={"asset_id": "asset"}).copy()
            f["date"] = pd.to_datetime(f.date)
            f["panel"] = Path(name).stem
            f["source"] = unit.name
            f["source_cutoff"] = pd.Timestamp(c["provenance"]["data_cutoff"])
            if (f.date > f.source_cutoff).any():
                raise ValueError(f"Source contains post-cutoff rows: {unit.name}")
            if f.duplicated(["asset", "date"]).any() or not np.isfinite(f.value).all():
                raise ValueError(f"Ambiguous/nonfinite source panel {unit.name}/{name}")
            frames.append(f[["panel", "asset", "date", "value", "source", "source_cutoff"]])
    donors = pd.concat(frames, ignore_index=True).sort_values(["source_cutoff", "source"])
    counts = donors.groupby(["panel", "asset", "date"]).value.nunique()
    union = donors.drop_duplicates(["panel", "asset", "date"], keep="last")
    meta = {
        "input_sha256": signature, "practice_units": len(units(root)),
        "source_rows": len(donors), "union_rows": len(union),
        "conflicting_keys": counts.gt(1).groupby(level=0).sum().to_dict(),
        "policy": "Exclude exemplar. Latest source cutoff then lexical source wins; revised vintage.",
        "panels": {p: {"rows": len(f), "assets": sorted(f.asset.unique().tolist()),
                         "start": str(f.date.min().date()), "end": str(f.date.max().date())}
                   for p, f in union.groupby("panel")},
    }
    donors.to_parquet(cache, index=False)
    union.to_parquet(out / "union.parquet", index=False)
    (out / "provenance.json").write_text(json.dumps(meta, indent=2) + "\n")
    return donors, meta


def panel_frames(donors: pd.DataFrame) -> dict[str, pd.DataFrame]:
    union = donors.drop_duplicates(["panel", "asset", "date"], keep="last")
    return {p + ".parquet": f[["date", "asset", "value"]].sort_values(["asset", "date"]).reset_index(drop=True)
            for p, f in union.groupby("panel")}


def panel_for(panels: dict, asset: str) -> str:
    return next(name for name in sorted(panels) if asset in set(panels[name].asset))


def is_monthly(s: pd.Series) -> bool:
    days, good = intervals(s)
    return bool(len(days) and good.any() and days[good].mean() > 20)


def target_labels(card: dict) -> tuple[dict, dict]:
    """Explicit dates/months first; business-day inference is labelled, never hidden."""
    dates = cell_metadata(card, "target_dates", "target_date")
    months = cell_metadata(card, "observation_periods", "observation_period")
    labels, kinds = {}, {}
    for a in card["targets"]["asset_ids"]:
        for h in card["targets"]["horizons"]:
            key = (a, h)
            if key in months:
                labels[key], kinds[key] = pd.Period(months[key], freq="M"), "explicit_month"
            elif key in dates:
                labels[key], kinds[key] = pd.Timestamp(dates[key]), "explicit_date"
            else:
                labels[key] = pd.Timestamp(card["provenance"]["data_cutoff"]) + pd.offsets.BDay(h)
                kinds[key] = "inferred_bday"
    return labels, kinds


def realized_from_series(s: pd.Series, asof: pd.Timestamp, label, kind: str, horizon: int) -> float:
    if isinstance(label, pd.Period):
        hits = s[s.index.to_period("M") == label]
    else:
        hits = s[s.index == label]
    if len(hits) != 1:
        raise ValueError("No unique exact target observation")
    if kind == "level":
        return float(hits.iloc[0])
    # Factor panels hold simple per-trading-observation returns. The target is additive log return.
    future = s.loc[(s.index > asof) & (s.index <= hits.index[0])]
    if len(future) < max(1, int(0.75*horizon)) or np.any(np.diff(future.index).astype('timedelta64[D]').astype(int) > 5):
        raise ValueError("Incomplete future return window")
    if (future <= -1).any():
        raise ValueError("Invalid simple return")
    return float(np.log1p(future).sum())


def write_unit(path: Path, card: dict, panels: dict, spec: dict) -> None:
    (path / "panels").mkdir(parents=True, exist_ok=True)
    (path / "card.toml").write_text(tomli_w.dumps(card))
    (path / "forecast_spec.json").write_text(json.dumps(spec, indent=2) + "\n")
    for name, f in panels.items():
        f.to_parquet(path / "panels" / name, index=False)


def synthetic(root: Path, out: Path, donors: pd.DataFrame, n_cards: int, seed: int) -> list[dict]:
    all_panels = panel_frames(donors)
    templates = units(root)
    rng = np.random.default_rng(seed)
    # Balanced rounds make the shape distribution differ by at most one card/template.
    roster = []
    while len(roster) < n_cards:
        roster.extend(rng.permutation(len(templates)).tolist())
    calendar = pd.bdate_range("2005-01-03", "2024-12-31")
    cases, used = [], set()
    for index, ti in enumerate(roster[:n_cards]):
        unit = templates[ti]
        template = read_card(unit / "card.toml")
        targets = copy.deepcopy(template["targets"])
        source_panels = read_panels(unit / "panels")
        originals = list(targets["asset_ids"])
        chosen = [panel_for(all_panels, a) for a in originals]
        replacements = {}
        # Early EM windows have no continuous future in 2005–2024. Mirror their
        # single-level FX shape on available G10 series, recording the substitution.
        for ai, name in enumerate(chosen):
            if Path(name).stem == "em_transfer_early":
                available = sorted(all_panels["g10_fx_daily.parquet"].asset.unique())
                replacement = available[ai % len(available)]
                replacements[originals[ai]] = replacement
                targets["asset_ids"][ai] = replacement
                chosen[ai] = "g10_fx_daily.parquet"
        names = sorted(set(chosen))
        selected = {name: all_panels[name] for name in names}
        source_hist = {a: history(source_panels, a, template["provenance"]["data_cutoff"]) for a in originals}
        monthly = all(is_monthly(s) for s in source_hist.values())
        original_asof = pd.Timestamp(template["provenance"]["data_cutoff"])
        original_labels, _ = target_labels(template)
        source_lag = {replacements.get(a,a): original_asof.to_period("M").ordinal - s.index[-1].to_period("M").ordinal
                      for a, s in source_hist.items()}
        series = {a: f.loc[f.asset == a].set_index("date").value.sort_index()
                  for name in names for a in targets["asset_ids"]
                  if a in set((f := selected[name]).asset)}
        for attempt in range(5000):
            asof = calendar[int(rng.integers(len(calendar)))]
            if (ti, asof) in used:
                continue
            input_panels = {name: f.loc[f.date <= asof].copy() for name, f in selected.items()}
            if monthly:
                for name, f in input_panels.items():
                    keep = pd.Series(True, index=f.index)
                    for a in targets["asset_ids"]:
                        last_period = asof.to_period("M") - source_lag[a]
                        keep &= (f.asset != a) | (f.date.dt.to_period("M") <= last_period)
                    input_panels[name] = f.loc[keep]
            if any(len(f.loc[f.asset == a]) < 30 for a in targets["asset_ids"]
                   for f in input_panels.values() if a in set(f.asset)):
                continue
            trial_targets = copy.deepcopy(targets)
            trial_targets.pop("target_dates", None)
            trial_targets.pop("observation_periods", None)
            trial_targets["target_frequency"] = "monthly" if monthly else "daily"
            if monthly:
                a0 = originals[0]
                trial_targets["observation_periods"] = [
                    str(asof.to_period("M") + (original_labels[a0,h].ordinal - original_asof.to_period("M").ordinal))
                    for h in targets["horizons"]]
            else:
                trial_targets["target_dates"] = [str((asof + pd.offsets.BDay(h)).date()) for h in targets["horizons"]]
            card = {
                "schema_version": "2.0",
                "task": {"id": f"synthetic-{seed}-{index:05d}", "track": "forecasting", "split": "public-dev"},
                "metadata": {"category": template["metadata"]["category"], "asset_panel": "+".join(Path(x).stem for x in names)},
                "provenance": {"data_cutoff": str(asof.date())},
                "text": {"cutoff": str(asof.date())},
                "environment": copy.deepcopy(template["environment"]),
                "scoring": copy.deepcopy(template["scoring"]), "targets": trial_targets,
            }
            labels, _ = target_labels(card)
            try:
                values = [{"asset": a, "horizon": h,
                           "value": realized_from_series(series[a], asof, labels[a,h], targets["target_type"], h)}
                          for a in targets["asset_ids"] for h in targets["horizons"]]
                from t2agent.m0 import distribution
                distribution(card, input_panels, str(asof.date()))
            except (ValueError, KeyError, IndexError):
                continue
            break
        else:
            raise ValueError(f"Cannot generate a labelled shape from {unit.name}")
        used.add((ti,asof))
        path = out / card["task"]["id"]
        spec = {"card_id": card["task"]["id"], "card_family": template["forecast_spec"]["card_family"],
                "targets": trial_targets, "panels": [{"panel_id": Path(x).stem} for x in names]}
        write_unit(path, card, input_panels, spec)
        pd.DataFrame(values).to_parquet(path / "realized.parquet", index=False)
        cases.append({"unit": str(path), "realized": str(path / "realized.parquet"),
                      "template": unit.name, "asset_substitutions": replacements,
                      "date_basis": "generated_month" if monthly else "generated_bday",
                      "monthly": monthly})
        if (index+1) % 100 == 0:
            print(f"Generated {index+1}/{n_cards} pseudo-cards", flush=True)
    return cases


def practice(root: Path, out: Path, donors: pd.DataFrame, *, strict_dates=False) -> tuple[list, list]:
    out.mkdir(parents=True, exist_ok=True)
    cases, unresolved = [], []
    # Build per-series donor indexes once. Every resolved card uses a complete
    # sibling vintage, never a stitched target window with the current unit in it.
    grouped = {(p,a): f for (p,a), f in donors.groupby(["panel", "asset"], sort=False)}
    for unit in units(root):
        card = read_card(unit / "card.toml")
        panels = read_panels(unit / "panels")
        labels, kinds = target_labels(card)
        values, provenance = [], []
        try:
            if strict_dates and "inferred_bday" in kinds.values():
                raise ValueError("Sealed target date; strict mode refuses business-day inference")
            for (a,h), label in labels.items():
                panel = Path(panel_for({n: f.rename(columns={"asset_id":"asset"}) for n,f in panels.items()}, a)).stem
                candidates = grouped[panel,a]
                candidates = candidates[candidates.source != unit.name]
                found = None
                for source, f in candidates.groupby("source", sort=False):
                    s = f.set_index("date").value.sort_index()
                    try:
                        value = realized_from_series(s, pd.Timestamp(card["provenance"]["data_cutoff"]), label,
                                                     card["targets"]["target_type"], h)
                    except ValueError:
                        continue
                    # Latest vintage wins deterministically; expose competing values.
                    option = (pd.Timestamp(f.source_cutoff.iloc[0]), source, value)
                    if found is None or option[:2] > found[:2]:
                        found = option
                if found is None:
                    raise ValueError(f"No sibling observation for {a}, {label}, horizon {h}")
                values.append({"asset":a,"horizon":h,"value":found[2]})
                provenance.append({"asset":a,"horizon":h,"target":str(label),"date_basis":kinds[a,h],
                                   "source":found[1],"source_cutoff":str(found[0].date())})
        except (ValueError, KeyError) as exc:
            unresolved.append({"unit":unit.name,"reason":str(exc)})
            continue
        path = out / unit.name
        path.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(values).to_parquet(path / "realized.parquet", index=False)
        (path / "provenance.json").write_text(json.dumps(provenance, indent=2)+"\n")
        cases.append({"unit":str(unit),"realized":str(path / "realized.parquet"),
                      "date_basis":"inferred_bday" if "inferred_bday" in kinds.values() else "explicit",
                      "provenance":provenance})
    return cases, unresolved
