#!/usr/bin/env bash
# Isolated updated evaluation environment. Never change release setup/pins.
set -euo pipefail
cd "$(dirname "$0")/.."
upstream=3b51e16b3f7c0fa0e56bcba323c2bb5e81b8bd56
if [[ ! -d vendor/current/.git ]]; then
  git clone https://github.com/Agenthon-2026/track2-forecasting-public.git vendor/current
fi
if [[ -n "$(git -C vendor/current status --porcelain)" ]]; then
  echo 'vendor/current is dirty; refusing to overwrite it' >&2; exit 1
fi
git -C vendor/current fetch origin "$upstream"
git -C vendor/current checkout --detach "$upstream"
python3.13 -m venv .venv-current
.venv-current/bin/python -m pip install -c reports/final_alignment/constraints-current.txt \
  -r requirements-runtime.txt jsonschema scipy tomli-w pytest \
  'qfbench2-common[data] @ git+https://github.com/Agenthon-2026/Agenthon2026-public.git@v2.6.1#subdirectory=common' \
  ./vendor/current
