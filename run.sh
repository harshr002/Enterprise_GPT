#!/usr/bin/env bash
# Local dev launcher.
set -e

# Create venv on first run
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

# Copy env template on first run
if [ ! -f ".env" ]; then
  echo "No .env found -> copying from .env.example (add your GEMINI_API_KEY!)"
  cp .env.example .env
fi

echo "Starting Infosys AI Knowledge Assistant on http://localhost:8000 ..."
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
