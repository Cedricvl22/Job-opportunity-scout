#!/usr/bin/env bash
# One-time setup for job-opportunity-scout. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"
python3 -m pip install -q -r requirements.txt
# Use an existing Chromium if present (PW_CHROMIUM_PATH), otherwise download Playwright's.
if [ ! -x "${PW_CHROMIUM_PATH:-/opt/pw-browsers/chromium}" ]; then
  python3 -m playwright install chromium
fi
python3 tests/test_offline.py
