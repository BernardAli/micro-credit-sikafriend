#!/usr/bin/env bash
# setup.sh — one-shot project setup for micro-credit standalone
# Usage: bash setup.sh

set -e

PYTHON=${PYTHON:-python3}
VENV_DIR=".venv"

echo ""
echo "=== Micro-Credit Standalone Setup ==="
echo ""

# 1. Create virtual environment
if [ ! -d "$VENV_DIR" ]; then
    echo "[1/5] Creating virtual environment..."
    $PYTHON -m venv "$VENV_DIR"
else
    echo "[1/5] Virtual environment already exists — skipping."
fi

# 2. Activate virtual environment
source "$VENV_DIR/bin/activate"

# 3. Install dependencies
echo "[2/5] Installing dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

# 4. Create .env if it doesn't exist
if [ ! -f ".env" ]; then
    echo "[3/5] Creating .env from .env.example..."
    cp .env.example .env
else
    echo "[3/5] .env already exists — skipping."
fi

# 5. Run migrations
echo "[4/5] Running database migrations..."
python manage.py migrate --run-syncdb

# 6. Create superuser
echo ""
echo "[5/5] Creating admin superuser..."
echo "      (You will be prompted for username, email, and password)"
echo ""
python manage.py createsuperuser

echo ""
echo "======================================================"
echo "  Setup complete! Start the server with:"
echo ""
echo "    source .venv/bin/activate"
echo "    python manage.py runserver"
echo ""
echo "  Then open: http://127.0.0.1:8000/"
echo "  Admin panel: http://127.0.0.1:8000/admin/"
echo "======================================================"
