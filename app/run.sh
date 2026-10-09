#!/usr/bin/with-contenv bashio
set -euo pipefail

export ELRAKNING_APP_TOKEN="$(bashio::config 'app_token')"
exec python3 -m elrakning_app.server
