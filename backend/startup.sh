#!/bin/bash
set -euo pipefail

cd /home/site/wwwroot

mkdir -p /home/site/data/generated_images
ln -sfn /home/site/data/generated_images generated_images 2>/dev/null || true

if [ -f requirements.txt ]; then
  python -m pip install --upgrade pip --quiet
  python -m pip install -r requirements.txt --quiet
fi

exec gunicorn app.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 2 \
  --bind "0.0.0.0:${WEBSITES_PORT:-8000}" \
  --timeout 300 \
  --access-logfile - \
  --error-logfile -
