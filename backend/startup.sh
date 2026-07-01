#!/bin/bash
set -euo pipefail

# Find the deployment root that contains app/main.py (Oryx may extract to /tmp/...).
APP_DIR=""
for candidate in "${APP_PATH:-}" /home/site/wwwroot /tmp/*; do
  [ -n "$candidate" ] || continue
  [ -d "$candidate" ] || continue
  if [ -f "$candidate/app/main.py" ]; then
    APP_DIR="$candidate"
    break
  fi
done

if [ -z "$APP_DIR" ]; then
  echo "ERROR: Could not find app/main.py under APP_PATH, wwwroot, or /tmp" >&2
  ls -la /home/site/wwwroot >&2 || true
  ls -la /tmp >&2 || true
  exit 1
fi

cd "$APP_DIR"
export PYTHONPATH="${APP_DIR}:${PYTHONPATH:-}"
echo "Starting API from ${APP_DIR}"

mkdir -p /home/site/data/generated_images
ln -sfn /home/site/data/generated_images generated_images 2>/dev/null || true

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
