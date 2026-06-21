#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../Backend"

if [ -f ".venv/bin/activate" ]; then
  source ".venv/bin/activate"
fi

python -m compileall app
pytest
