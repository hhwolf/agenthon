"""Fixed Phase 4 label-to-number constants; no fitted values or mapping code.

SOLVER-PLAYBOOK §§3–5 motivate the rules; the Phase 4 specification supplies
these numerical starting values. Implementation lives in text_overlay.py.
"""

DEFAULT_LAMBDA = 0.5
ENV_LAMBDA = "TEXT_LAYER_LAMBDA"
REGIME_VOL = {"calm": 1.0, "elevated": 1.25, "crisis": 1.6}
REGIME_TAIL = {"calm": 1.0, "elevated": 1.0, "crisis": 1.5}
EVENT_VOL_FLOOR = {"none": 1.0, "scheduled_binary": 1.15, "ongoing": 1.15}
EVENT_TAIL = {"none": 1.0, "scheduled_binary": 1.25, "ongoing": 1.0}
DIRECTION_DRIFT = {"strong_down": -0.5, "down": -0.25, "none": 0.0, "up": 0.25, "strong_up": 0.5}
BINARY_BRANCH_DRIFT = 1.0
BRANCH_PROB_CLIP = (0.2, 0.8)
BINARY_MEAN_DRIFT_LIMIT = 0.6
DISAGREEMENT_VOL_FLOOR = 1.15
F4_TAIL_MULT = 1.5
TAIL_QUANTILE = 0.95
