"""Text-aware forecaster: numeric_v1.1 draws adjusted by the text layer's labels through text_map.

Selected with ``--forecaster text_v1`` (CLI) or ``FORECASTER=t2agent.text_v1:forecast`` (evaluation).
``numeric_v1_1.forecast`` (the image default) is untouched; the signal is passed through its ``text_signal`` hook.
Environment: ``TEXT_LAYER_LAMBDA`` (default 0.5), ``TEXT_LAYER_MODE`` (labels | notes_only), and the
House variables. Any text-layer problem degrades to the numeric forecast and is written to the rationale.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import numeric_v1_1 as engine
from .contracts import CallBudget
from .text_layer import read_text
from .text_layer.summary import numeric_summary_from
from .text_map import apply_text_map, lambda_from_env


def forecast(card, panels, text_dir, asof, n_draws=2000, seed=None):
    signal = None
    note = ""
    try:
        if text_dir is None:
            note = "Text layer skipped: no text directory was supplied."
        else:
            unit_dir = Path(text_dir).parent
            summary = numeric_summary_from(card, panels, asof)
            raw = read_text(unit_dir, summary, CallBudget())
            lam = lambda_from_env()
            signal = apply_text_map(raw, summary, lam)
            note = signal.rationale_md
    except Exception as exc:  # noqa: BLE001 - never let text break the forecast
        signal = None
        note = f"Text layer unavailable: {type(exc).__name__}: {exc}"
    frame = engine.forecast(card, panels, None, asof, n_draws, seed, text_signal=signal)
    frame.attrs["rationale"] = (frame.attrs.get("rationale") or "").rstrip() + "\n\n" + note.rstrip() + "\n"
    frame.attrs["text_signal"] = signal
    return frame


def make_forecaster(mode: str | None = None, lam: float | None = None, table: dict | None = None):
    """Env-free variant for ablations: ``FORECASTER=t2agent.text_v1:<name>`` keys the evaluator's output.

    ``table`` overrides label->number constants (see ``text_map.TUNABLE``) for pre-declared table variants.
    """

    def _forecast(card, panels, text_dir, asof, n_draws=2000, seed=None):
        signal = None
        note = ""
        try:
            if text_dir is None:
                note = "Text layer skipped: no text directory was supplied."
            else:
                summary = numeric_summary_from(card, panels, asof)
                raw = read_text(Path(text_dir).parent, summary, CallBudget(), mode=mode)
                signal = apply_text_map(raw, summary, lambda_from_env() if lam is None else lam, table=table)
                note = signal.rationale_md
        except Exception as exc:  # noqa: BLE001
            signal = None
            note = f"Text layer unavailable: {type(exc).__name__}: {exc}"
        frame = engine.forecast(card, panels, None, asof, n_draws, seed, text_signal=signal)
        frame.attrs["rationale"] = (frame.attrs.get("rationale") or "").rstrip() + "\n\n" + note.rstrip() + "\n"
        frame.attrs["text_signal"] = signal
        return frame

    _forecast.__name__ = f"forecast_{mode or 'labels'}_lambda_{lam if lam is not None else 'env'}"
    return _forecast


forecast_notes_only_l05 = make_forecaster("notes_only", 0.5)
forecast_notes_only_l10 = make_forecaster("notes_only", 1.0)
forecast_labels_l05 = make_forecaster("labels", 0.5)
forecast_labels_l10 = make_forecaster("labels", 1.0)
# Pre-declared table variants (Phase 4 ablation; scored from the cache, no network):
forecast_labels_l075 = make_forecaster("labels", 0.75)
forecast_labels_l05_dis_half = make_forecaster("labels", 0.5, {"DISAGREEMENT_DRIFT_FACTOR": 0.5})
forecast_labels_l05_branch_075 = make_forecaster("labels", 0.5, {"BINARY_BRANCH_DRIFT": 0.75})
