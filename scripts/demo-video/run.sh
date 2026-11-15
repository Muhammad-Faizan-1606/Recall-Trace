#!/bin/bash
# Run (and record) the walkthrough. FAST=1 skips video and pauses; arguments pick chapters.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/demo.env.sh"
cd "$HERE"
exec node demo.js "$@"
