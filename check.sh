#!/usr/bin/env sh
# Minimal: format with black, then lint with flake8.
# Requires: pip install -r requirements-dev.txt
set -e

echo "== black =="
black .

echo "== flake8 =="
flake8 .

echo "OK"
