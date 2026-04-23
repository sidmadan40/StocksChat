#!/bin/sh
# Start script for the Streamlit frontend service on Railway.
# Railway injects $PORT automatically.
exec streamlit run frontend/app.py \
  --server.address 0.0.0.0 \
  --server.port "${PORT:-8501}" \
  --server.headless true \
  --server.enableCORS false \
  --server.enableXsrfProtection false
