#!/bin/sh
# Start script for the FastAPI backend service on Railway.
# Railway injects $PORT automatically.
exec uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-8000}"
