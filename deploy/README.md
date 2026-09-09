# Deploying Eldian Core

Written for someone who knows `ssh`, `nano` and copy/paste. Nothing more.

**The short version, once set up:** push to GitHub, then run ONE command on the
server:

```bash
cd /opt/eldiancore && ./deploy/update.sh
```

---

## What gets installed

| Thing | Value | Why |
|---|---|---|
| App directory | `/opt/eldiancore` | Separate from any existing app |
| Backend port | `8001` | 8000 is taken by the existing app |
| Frontend port | `3001` | 3000 is taken |
| Services | `eldiancore-api`, `eldiancore-web` | Distinct names — never `orbit-*` |

Both services bind to `127.0.0.1` only. Nginx is the only thing exposed.

---

## STEP 1 — Push your code to GitHub

On your PC, from the project folder:

```bash
git add -A
git commit -m "Add deployment scripts"
git remote add origin https://github.com/YOURNAME/YOURREPO.git
git push -u origin main
```

**Success looks like:** a list of files, ending in `main -> main`.

⚠️ Your secrets (`backend/.env`, `.env.local`) are gitignored and will NOT be
uploaded. That is intentional — you create them on the server in Step 4.

---

## STEP 2 — Add the DNS record

In Hostinger → your domain → DNS:

| Type | Name | Points to | TTL |
|---|---|---|---|
| A | `app` (or your chosen subdomain) | your VPS IP | default |

**Do this BEFORE Step 6.** Certbot fails if DNS has not propagated.

Check it worked (from your PC), after 5–15 minutes:

```bash
nslookup app.orb-itworks.com
```

**Success looks like:** your VPS IP in the answer.

---

## STEP 3 — Clone the project onto the server

```bash
ssh root@YOUR_VPS_IP
sudo mkdir -p /opt/eldiancore
sudo chown -R $USER:$USER /opt/eldiancore
git clone https://github.com/YOURNAME/YOURREPO.git /opt/eldiancore
cd /opt/eldiancore
```

**Success looks like:** `Resolving deltas: 100%` and files present after `ls`.

---

## STEP 4 — Create the secrets file

```bash
nano /opt/eldiancore/backend/.env
```

Copy the contents of `backend/.env.example` and fill in your real values.
Save with `Ctrl+O`, `Enter`, then exit with `Ctrl+X`.

⚠️ **Wrap any value containing `#` in double quotes.** An unquoted `#` starts a
comment and silently cuts the value short — this looks exactly like a wrong
password and is miserable to debug.

⚠️ **`ENCRYPTION_SECRET` must match the one you already use.** If it differs,
API keys and email passwords saved in the database cannot be decrypted.

Then lock the file down:

```bash
chmod 600 /opt/eldiancore/backend/.env
```

---

## STEP 5 — Run the setup script

```bash
cd /opt/eldiancore
./deploy/setup-vps.sh
```

Takes 5–10 minutes (Playwright downloads a browser).

**Success looks like:**

```
eldiancore-api: active
eldiancore-web: active
backend health: 200
```

If it says a port is in use, or warns about low memory, stop and read the
message — it tells you what to do.

---

## STEP 6 — Nginx and SSL

⚠️ **Read this before running anything.** The existing site's config uses
`listen 80 default_server` with `server_name _;`, which catches *every*
hostname. Two sites cannot both be the catch-all.

First look at what is there:

```bash
cat /etc/nginx/sites-available/orbitscanner
```

If it says `server_name _;`, change it to the real hostname:

```bash
sudo nano /etc/nginx/sites-available/orbitscanner
# change:  server_name _;
# to:      server_name scan.orb-itworks.com;
```

Now add the new site:

```bash
sudo cp /opt/eldiancore/deploy/nginx-eldiancore.conf /etc/nginx/sites-available/eldiancore
sudo nano /etc/nginx/sites-available/eldiancore
# replace SUBDOMAIN_PLACEHOLDER with e.g. app.orb-itworks.com

sudo ln -sf /etc/nginx/sites-available/eldiancore /etc/nginx/sites-enabled/eldiancore
sudo nginx -t
```

**`nginx -t` must say `test is successful`.** If it does not, do NOT reload —
fix the error first, or you take the existing site down too.

```bash
sudo systemctl reload nginx
```

Then SSL, for the NEW subdomain only:

```bash
sudo certbot --nginx -d app.orb-itworks.com
```

⚠️ Never pass the existing domain here as well — that rewrites its config.

---

## STEP 7 — Check it works

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://app.orb-itworks.com
curl -s -o /dev/null -w "%{http_code}\n" https://app.orb-itworks.com/api/health
curl -s -o /dev/null -w "%{http_code}\n" https://scan.orb-itworks.com
```

**All three should print `200`** — the third proves the existing site still works.

---

## Updating after the first deploy

On your PC:

```bash
git add -A && git commit -m "your change" && git push
```

On the server:

```bash
cd /opt/eldiancore && ./deploy/update.sh
```

That pulls, installs, rebuilds, restarts, and verifies. It prints
`Deploy complete` on success, or the failing service's logs on failure.

⚠️ **`NEXT_PUBLIC_*` variables are baked in at build time, not read at
runtime.** If you change one, you must rebuild — a restart alone does nothing.
`update.sh` rebuilds every time, so editing `.env.local` then running it is
the correct order.

---

## If something breaks

```bash
systemctl status eldiancore-api          # is it running?
journalctl -u eldiancore-api -n 50       # why did it stop?
journalctl -u eldiancore-web -n 50
sudo nginx -t                            # is the proxy config valid?
```

The existing app is untouched by all of the above. Its services are
`orbit-api` and `orbit-web` — never restart those to fix this app.
