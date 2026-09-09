#!/usr/bin/env bash
# One-time setup for Eldian Core on a VPS that ALREADY runs another app.
# Idempotent: safe to run again.
#
# Deliberately uses ports 8001/3001 and service names eldiancore-* so it can
# never collide with an existing app on 8000/3000 or orbit-* services.
set -euo pipefail

APP_DIR="/opt/eldiancore"
API_PORT=8001
WEB_PORT=3001
SERVICE_USER="${SUDO_USER:-$USER}"

echo "==> Checking ports are free"
for p in "$API_PORT" "$WEB_PORT"; do
  if ss -tlnp 2>/dev/null | grep -q ":$p "; then
    echo "    ERROR: port $p is already in use. Pick another and edit this script."
    exit 1
  fi
  echo "    port $p is free"
done

echo "==> Checking memory (Node builds are memory-hungry)"
FREE_MB=$(free -m | awk 'NR==2{print $7}')
echo "    available: ${FREE_MB} MB"
if [ "$FREE_MB" -lt 1200 ]; then
  echo "    WARNING: low memory. Add swap before building, or the build may"
  echo "             OOM and kill the app already running on this server:"
  echo "               sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile"
  echo "               sudo mkswap /swapfile && sudo swapon /swapfile"
  read -rp "    Continue anyway? [y/N] " ok
  [ "$ok" = "y" ] || exit 1
fi

echo "==> System packages"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  python3-venv python3-pip git curl nginx >/dev/null
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - >/dev/null 2>&1
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nodejs >/dev/null
fi
echo "    node $(node --version), python $(python3 --version | cut -d' ' -f2)"

echo "==> Python environment"
cd "$APP_DIR"
[ -d venv ] || python3 -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r backend/requirements.txt

echo "==> Playwright + Chromium (needed by the Google Maps scraper)"
./venv/bin/pip install -q playwright
sudo ./venv/bin/playwright install-deps chromium >/dev/null 2>&1 || true
./venv/bin/playwright install chromium 2>&1 | tail -1

echo "==> Frontend build"
# NEXT_PUBLIC_* is baked in at build time — .env.local must exist FIRST.
[ -f .env.local ] || echo 'NEXT_PUBLIC_API_BASE=/api' > .env.local
npm install --no-audit --no-fund --silent 2>&1 | tail -1
npm run build 2>&1 | tail -3

echo "==> systemd services"
# Paths are quoted so a directory with spaces can never cause status=203/EXEC.
sudo tee /etc/systemd/system/eldiancore-api.service >/dev/null <<UNIT
[Unit]
Description=Eldian Core API (FastAPI)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${APP_DIR}/backend
Environment=PYTHONUNBUFFERED=1
ExecStart=${APP_DIR}/venv/bin/uvicorn app_entry:app --host 127.0.0.1 --port ${API_PORT}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

sudo tee /etc/systemd/system/eldiancore-web.service >/dev/null <<UNIT
[Unit]
Description=Eldian Core web (Next.js)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${APP_DIR}
Environment=NODE_ENV=production
Environment=PORT=${WEB_PORT}
ExecStart=/usr/bin/npm run start
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

# Allow restarting ONLY these two services without a password.
echo "${SERVICE_USER} ALL=(ALL) NOPASSWD: /bin/systemctl restart eldiancore-api, /bin/systemctl restart eldiancore-web" \
  | sudo tee /etc/sudoers.d/eldiancore >/dev/null
sudo chmod 440 /etc/sudoers.d/eldiancore

sudo systemctl daemon-reload
sudo systemctl enable --now eldiancore-api eldiancore-web
sleep 10

echo "==> Status"
for svc in eldiancore-api eldiancore-web; do
  echo "    $svc: $(systemctl is-active "$svc")"
done
echo "    backend health: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:${API_PORT}/health || echo 000)"
echo
echo "Services are running on 127.0.0.1 only. Nginx is configured separately"
echo "(see deploy/README.md) so the existing site is never touched."
