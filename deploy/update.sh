#!/usr/bin/env bash
# Pull the latest code and restart. THIS is the one command you run after
# pushing to GitHub:   cd /opt/eldiancore && ./deploy/update.sh
set -euo pipefail

APP_DIR="/opt/eldiancore"
cd "$APP_DIR"

echo "==> Pulling latest code"
git fetch --all --quiet
git reset --hard origin/main --quiet
echo "    now at: $(git log -1 --format='%h %s')"

echo "==> Backend dependencies"
./venv/bin/pip install -q -r backend/requirements.txt

echo "==> Frontend dependencies"
npm ci --no-audit --no-fund --silent 2>&1 | tail -1 || npm install --no-audit --no-fund --silent 2>&1 | tail -1

# NEXT_PUBLIC_* values are baked in at BUILD time, not read at runtime.
# So .env.local must be correct BEFORE this build runs.
echo "==> Building frontend (this is the slow part)"
npm run build 2>&1 | tail -4

echo "==> Restarting services"
sudo systemctl restart eldiancore-api
sudo systemctl restart eldiancore-web
sleep 8

echo "==> Verifying"
FAILED=0
for svc in eldiancore-api eldiancore-web; do
  if systemctl is-active --quiet "$svc"; then
    echo "    OK      $svc"
  else
    echo "    FAILED  $svc"
    journalctl -u "$svc" -n 20 --no-pager
    FAILED=1
  fi
done

CODE=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8001/health || echo 000)
echo "    backend health: $CODE"
[ "$CODE" = "200" ] || FAILED=1

if [ "$FAILED" -ne 0 ]; then
  echo "==> DEPLOY FAILED — see errors above"
  exit 1
fi
echo "==> Deploy complete"
