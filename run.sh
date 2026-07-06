#!/usr/bin/env bash
# run.sh — start the development server
set -e

if [ ! -d ".venv" ]; then
    echo "Run bash setup.sh first to install dependencies."
    exit 1
fi

source .venv/bin/activate
python manage.py runserver "${1:-127.0.0.1:8000}"
