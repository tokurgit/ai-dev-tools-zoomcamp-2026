#!/usr/bin/env bash
# deploy/deploy.sh — run for every release. Safe to re-run.
#
# git fetch + checkout GIT_REF, `uv sync --frozen`, migrate, collectstatic,
# restart Gunicorn, reload Nginx only if its rendered config actually
# changed, then run smoke.sh. Exits non-zero (without stopping the old
# Gunicorn process first) if anything fails, so a bad release never takes
# the site down — see README.md — "Idempotency and failure behaviour".
#
# Usage (as the app user, or root — see README.md):
#   ./deploy.sh [path-to-app.env]      # defaults to ./app.env, falls back
#                                       # to the installed /etc/<APP_NAME>/app.env
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"

ENV_FILE="${1:-$SCRIPT_DIR/app.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  # bootstrap.sh installs the real app.env under /etc/<APP_NAME>/; a routine
  # `./deploy.sh` run (no argument, and deploy/app.env not present on this
  # checkout) falls back to whichever /etc/*/app.env bootstrap.sh installed,
  # so day-to-day deploys don't need an explicit path.
  for candidate in /etc/*/app.env; do
    if [[ -f "$candidate" ]]; then
      ENV_FILE="$candidate"
      break
    fi
  done
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing app.env — pass a path, or run from a box bootstrap.sh already set up" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${APP_NAME:?APP_NAME must be set in $ENV_FILE}"
: "${APP_DIR:?APP_DIR must be set in $ENV_FILE}"
: "${DOMAIN:?DOMAIN must be set in $ENV_FILE}"
: "${GIT_REF:?GIT_REF must be set in $ENV_FILE}"

echo "==> [1/6] fetching and checking out $GIT_REF"
git -C "$APP_DIR" fetch --tags
git -C "$APP_DIR" checkout "$GIT_REF"

echo "==> [2/6] syncing dependencies"
(cd "$APP_DIR" && uv sync --frozen)

echo "==> [3/6] applying migrations"
(cd "$APP_DIR" && uv run python manage.py migrate --noinput)

echo "==> [4/6] collecting static files"
(cd "$APP_DIR" && uv run python manage.py collectstatic --noinput)

echo "==> [5/6] restarting $APP_NAME and reloading Nginx if it changed"
# Restart, don't stop-then-start: if the new code fails to boot, systemd's
# Restart=on-failure keeps retrying the *new* release rather than this
# script leaving the app down. `smoke.sh` below is what actually tells you
# whether the restart produced a healthy process.
systemctl restart "$APP_NAME"

NGINX_TEMPLATE="$SCRIPT_DIR/templates/nginx.conf"
NGINX_CACHE="/etc/$APP_NAME/nginx.conf.rendered"
if [[ -f "$NGINX_TEMPLATE" && -f "$NGINX_CACHE" ]]; then
  RENDERED="$(envsubst '${APP_NAME} ${APP_DIR} ${DOMAIN}' < "$NGINX_TEMPLATE")"
  # Diff against the cached *plain template* rendering bootstrap.sh saved,
  # never against the live /etc/nginx/sites-available/$APP_NAME file —
  # certbot edits that one in place to add the TLS block, so comparing
  # against it would look "changed" on every run and clobber HTTPS. See
  # bootstrap.sh's step 6 and README.md — "Nginx and certbot".
  if [[ "$RENDERED" != "$(cat "$NGINX_CACHE")" ]]; then
    echo "    nginx.conf template changed — re-rendering and reloading"
    echo "    NOTE: this overwrites any certbot TLS edits on the live file."
    echo "    If this box serves HTTPS, re-run: certbot --nginx -d \"$DOMAIN\""
    echo "$RENDERED" > "/etc/nginx/sites-available/$APP_NAME"
    echo "$RENDERED" > "$NGINX_CACHE"
    nginx -t
    systemctl reload nginx
  else
    echo "    nginx.conf unchanged — leaving the live config (and any certbot TLS block) alone"
  fi
else
  echo "    no cached nginx.conf.rendered found (not bootstrapped by this deploy/ yet) — skipping"
fi

echo "==> [6/6] smoke test"
if ! "$SCRIPT_DIR/smoke.sh" "$DOMAIN"; then
  echo "smoke test failed — the previous release's process was NOT stopped by this" >&2
  echo "script, but $APP_NAME is now running the new code and failed its own health" >&2
  echo "check. Investigate (journalctl -u $APP_NAME), then either fix and re-run" >&2
  echo "deploy.sh, or roll back: set GIT_REF to the previous tag/SHA and re-run." >&2
  exit 1
fi

echo "==> deploy of $GIT_REF complete"
