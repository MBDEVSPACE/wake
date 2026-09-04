#!/bin/sh
# Build and run Wake-on-LAN directly on your ZimaOS box - no registry needed.
#
#   ssh into ZimaOS, then:
#     sh install-on-zima.sh
#
# Afterwards the app is reachable at http://<zima-ip>:8055 and the image
# "wake-on-lan:local" exists locally, so the ZimaOS Custom Install flow can
# adopt it using docker-compose.local.yml.
set -eu

PORT="${WOL_WEB_PORT:-8055}"
DATA="${WOL_DATA_DIR:-/DATA/AppData/wake-on-lan/config}"
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

echo "==> Building wake-on-lan:local"
docker build -t wake-on-lan:local "$DIR"

echo "==> Starting container on port $PORT"
mkdir -p "$DATA"
docker rm -f wake-on-lan >/dev/null 2>&1 || true
docker run -d \
  --name wake-on-lan \
  --network host \
  --restart unless-stopped \
  -e WOL_WEB_PORT="$PORT" \
  -e WOL_PIN="${WOL_PIN:-}" \
  -v "$DATA":/config \
  wake-on-lan:local

echo
echo "Done. Open http://$(hostname -I 2>/dev/null | awk '{print $1}'):$PORT"
echo "To show it on the ZimaOS dashboard, use App Store -> Custom Install and"
echo "import docker-compose.local.yml from this directory."
