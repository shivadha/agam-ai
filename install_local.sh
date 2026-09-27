#!/usr/bin/env bash
# AGAM AI Studio — one-command local setup (Linux / macOS).
# Run this after every `git pull`.
set -u
cd "$(dirname "$0")"
python3 scripts/install_local.py "$@"
