#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Install the hash-locked development environment using scripts/setup.sh first.
# Audit results require current advisory data; preserve TLS verification/proxy trust.
.venv/bin/pip-audit --disable-pip --no-deps -r requirements.txt
.venv/bin/pip-audit --disable-pip --no-deps -r requirements-dev.txt
.venv/bin/bandit -r app -q
