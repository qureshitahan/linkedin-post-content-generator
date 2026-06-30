#!/bin/bash
set -euo pipefail

cd /home/site/wwwroot

# Serve the pre-built SPA from CI (dist/ is deployed to wwwroot).
exec npx --yes serve@14.2.4 -s . -l "${WEBSITES_PORT:-8080}"
