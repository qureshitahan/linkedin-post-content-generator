#!/bin/bash
set -euo pipefail

# Oryx extracts the deployed package to APP_PATH (/tmp/...) on Linux App Service.
# cd + PYTHONPATH must point at the folder that contains the `app` package.
if [ -n "${APP_PATH:-}" ] && [ -d "${APP_PATH}/app" ]; then
  APP_DIR="$APP_PATH"
elif [ -d /home/site/wwwroot/app ]; then
  APP_DIR=/home/site/wwwroot
else
  APP_DIR="${APP_PATH:-/home/site/wwwroot}"
fi

cd "$APP_DIR"
export PYTHONPATH="${APP_DIR}:${PYTHONPATH:-}"

mkdir -p /home/site/data/generated_images
ln -sfn /home/site/data/generated_images generated_images 2>/dev/null || true

# Skip pip if Oryx already created antenv during deployment build.
if [ -f requirements.txt ] && [ ! -d "${APP_DIR}/antenv" ]; then
  python -m pip install --upgrade pip --quiet
  python -m pip install -r requirements.txt --quiet
fi

exec gunicorn app.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 1 \
  --bind "0.0.0.0:${WEBSITES_PORT:-8000}" \
  --timeout 300 \
  --access-logfile - \
  --error-logfile -
