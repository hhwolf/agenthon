#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
revision=b9c663d239a0e6b86ebd3f3f2d5aead88516067d
if [ ! -d vendor/track2/.git ]; then
  mkdir -p vendor
  git clone https://github.com/Agenthon-2026/track2-forecasting-public.git vendor/track2
  git -C vendor/track2 checkout --detach "$revision"
fi
if [ "$(git -C vendor/track2 rev-parse HEAD)" != "$revision" ]; then
  echo "vendor/track2 is not the documented revision; use a separate checkout or update the provenance intentionally." >&2
  exit 1
fi
if [ ! -d .venv ]; then
  "${PYTHON_BOOTSTRAP:-python3.13}" -m venv .venv
fi
.venv/bin/python -m pip install -c constraints-eval.txt -r requirements-runtime.txt 'jsonschema==4.23.0' \
  'qfbench2-common[data] @ git+https://github.com/Agenthon-2026/Agenthon2026-public.git@v2.6.0#subdirectory=common'
.venv/bin/python -m pip install -c constraints-eval.txt ./vendor/track2 -e '.[eval]'
