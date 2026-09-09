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

# The API needs ~15s on a cold start: DNS resolution plus the first MongoDB
# Atlas connection. A fixed sleep guesses wrong and reports a false failure on
# a backend that came up fine, so poll until it answers instead.
# `curl ... || echo 000` would APPEND to curl's own output on failure (giving
# the "000000" that looked like a broken status code), so -w is used alone and
# a non-zero exit is swallowed with `|| true`.
CODE=000
for i in $(seq 1 30); do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8001/health || true)
  [ -z "$CODE" ] && CODE=000
  [ "$CODE" = "200" ] && break
  sleep 2
done
echo "    backend health: $CODE (after $((i * 2))s)"
[ "$CODE" = "200" ] || FAILED=1

# The existing production app must be untouched by our deploy. Checking it here
# means a mistake surfaces now rather than when a customer finds it.
EXISTING=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 https://scan.orb-itworks.com || true)
echo "    existing site (scan.orb-itworks.com): ${EXISTING:-000}"
if [ "${EXISTING:-000}" != "200" ]; then
  echo "    WARNING: the pre-existing app is not returning 200 — investigate before continuing."
fi

if [ "$FAILED" -ne 0 ]; then
  echo "==> DEPLOY FAILED — see errors above"
  exit 1
fi
echo "==> Deploy complete"
