#!/usr/bin/env bash
# Pull the latest code and restart. THIS is the one command you run after
# pushing to GitHub:   cd /opt/eldiancore && ./deploy/update.sh
set -euo pipefail

APP_DIR="/opt/eldiancore"
cd "$APP_DIR"

# Record what we are on BEFORE pulling, so each step can ask "did anything I
# care about actually change?" instead of redoing its work every time.
#
# Measured on the VPS, 2026-11-21, a backend-only commit:
#     pip install .......... 34s
#     npm ci ............... 15m 53s
#     npm run build ........ 21m 2s
#     total ................ ~37 minutes
#
# Neither npm step had anything to do: no frontend file and no dependency had
# changed. `npm ci` deletes all 690MB of node_modules and reinstalls from
# scratch by design (its `sys` time was 7m51s - filesystem churn, not
# downloading), and `next build` rebuilt output identical to what was already
# there. A deploy that slow stops being run, which is its own failure: this
# one had sat unrun while three fixes waited.
OLD_REV="$(git rev-parse HEAD)"

echo "==> Pulling latest code"
git fetch --all --quiet
git reset --hard origin/main --quiet
NEW_REV="$(git rev-parse HEAD)"
echo "    now at: $(git log -1 --format='%h %s')"

# What changed between the two revisions? Empty on a first deploy or a forced
# rebuild, in which case every step below runs, which is the safe default.
if [ "$OLD_REV" = "$NEW_REV" ]; then
  CHANGED=""          # already up to date; nothing changed by definition
else
  CHANGED="$(git diff --name-only "$OLD_REV" "$NEW_REV" || true)"
fi

# FORCE=1 ./deploy/update.sh rebuilds everything regardless. Use it when a
# build looks wrong, or after changing .env.local - NEXT_PUBLIC_* values are
# baked in at build time, and env files are not in git, so no diff can see
# them.
FORCE="${FORCE:-0}"

changed_any() {
  [ "$FORCE" = "1" ] && return 0
  [ -z "$CHANGED" ] && return 1
  local pattern
  for pattern in "$@"; do
    if echo "$CHANGED" | grep -qE "$pattern"; then return 0; fi
  done
  return 1
}

echo "==> Backend dependencies"
if changed_any '^backend/requirements\.txt$'; then
  ./venv/bin/pip install -q -r backend/requirements.txt
  echo "    installed"
else
  echo "    skipped (requirements.txt unchanged)"
fi

echo "==> Frontend dependencies"
# `npm ci` is correct but expensive: it wipes node_modules every run. It is
# needed only when the lockfile moved, or when node_modules is missing.
if [ ! -d node_modules ]; then
  echo "    node_modules missing - installing"
  npm ci --no-audit --no-fund --silent 2>&1 | tail -1 \
    || npm install --no-audit --no-fund --silent 2>&1 | tail -1
elif changed_any '^package-lock\.json$' '^package\.json$'; then
  echo "    lockfile changed - installing"
  npm ci --no-audit --no-fund --silent 2>&1 | tail -1 \
    || npm install --no-audit --no-fund --silent 2>&1 | tail -1
else
  echo "    skipped (no dependency change)"
fi

echo "==> Frontend build"
# The frontend is only rebuilt when something it is built FROM changed. A
# backend-only commit cannot alter the output, so 21 minutes of CPU would
# produce a byte-identical .next directory.
#
# NEXT_PUBLIC_* values are baked in at BUILD time, not read at runtime, and
# .env.local is not in git - so use FORCE=1 after editing it.
if [ ! -d .next ]; then
  echo "    no previous build - building (slow)"
  npm run build 2>&1 | tail -4
elif changed_any '^app/' '^components/' '^lib/' '^types/' '^public/' \
                 '^package(-lock)?\.json$' '^next\.config\.' '^tsconfig\.json$' \
                 '\.(tsx?|jsx?|css|scss)$'; then
  echo "    frontend sources changed - building (slow)"
  npm run build 2>&1 | tail -4
else
  echo "    skipped (no frontend change) - use FORCE=1 to rebuild anyway"
fi

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

# The API's cold start is DNS resolution, the first MongoDB Atlas connection,
# agent seeding and 15 index checks. Measured at ~74s on this server, against
# a window that was 60s - so a backend that came up perfectly well was
# reported as "DEPLOY FAILED", three deploys in a row, while the health
# endpoint answered 200 fifteen seconds later. 180s leaves real headroom; the
# loop exits as soon as it gets a 200, so a fast start still costs nothing.
#
# `curl ... || echo 000` would APPEND to curl's own output on failure (giving
# the "000000" that looked like a broken status code), so -w is used alone and
# a non-zero exit is swallowed with `|| true`.
CODE=000
WAITED=0
for i in $(seq 1 90); do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8001/health || true)
  [ -z "$CODE" ] && CODE=000
  WAITED=$((i * 2))
  [ "$CODE" = "200" ] && break
  sleep 2
done
echo "    backend health: $CODE (after ${WAITED}s)"
[ "$CODE" = "200" ] || FAILED=1

# The existing production app must be untouched by our deploy. Checking it here
# means a mistake surfaces now rather than when a customer finds it.
#
# Retried rather than checked once: the frontend build drove this machine into
# memory pressure with no swap configured, and nginx briefly returned 000
# mid-deploy on an app this deploy never touched. A single probe turned that
# into a false alarm about the customer-facing site. Swap is configured now,
# but a transient blip should still not read as an outage.
EXISTING=000
for i in 1 2 3; do
  EXISTING=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 https://scan.orb-itworks.com || true)
  [ -z "$EXISTING" ] && EXISTING=000
  [ "$EXISTING" = "200" ] && break
  sleep 3
done
echo "    existing site (scan.orb-itworks.com): ${EXISTING}"
if [ "${EXISTING}" != "200" ]; then
  echo "    WARNING: the pre-existing app is not returning 200 — investigate before continuing."
fi

if [ "$FAILED" -ne 0 ]; then
  echo "==> DEPLOY FAILED — see errors above"
  exit 1
fi
echo "==> Deploy complete"
