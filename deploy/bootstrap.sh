#!/usr/bin/env bash
# deploy/bootstrap.sh — fresh-box / recovery only.
#
# Prepares a blank Ubuntu 24.04 box to run this app: installs system
# packages and uv, creates APP_USER/APP_DIR, clones REPO_URL at GIT_REF,
# installs app.env to a root-readable path, renders and installs the Nginx
# site and the Gunicorn/daily-import systemd units, and obtains a TLS
# certificate. It ends by invoking deploy.sh, which does the actual
# migrate/collectstatic/restart/smoke-test.
#
# Every step is guarded so re-running this after a partial failure mostly
# succeeds (see README.md — "Idempotency"). deploy.sh, not this script, is
# what you re-run for routine releases.
#
# Usage (as root, on the target box):
#   ./bootstrap.sh [path-to-app.env]      # defaults to ./app.env
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"

if [[ ${EUID} -ne 0 ]]; then
  echo "bootstrap.sh must run as root (try: sudo ./bootstrap.sh)" >&2
  exit 1
fi

ENV_FILE="${1:-$SCRIPT_DIR/app.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing $ENV_FILE" >&2
  echo "copy deploy/app.env.example to deploy/app.env and fill it in first" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${APP_NAME:?APP_NAME must be set in $ENV_FILE}"
: "${APP_USER:?APP_USER must be set in $ENV_FILE}"
: "${APP_DIR:?APP_DIR must be set in $ENV_FILE}"
: "${DOMAIN:?DOMAIN must be set in $ENV_FILE}"
: "${REPO_URL:?REPO_URL must be set in $ENV_FILE}"
: "${GIT_REF:?GIT_REF must be set in $ENV_FILE}"
: "${PYTHON_VERSION:?PYTHON_VERSION must be set in $ENV_FILE}"
: "${GUNICORN_WORKERS:?GUNICORN_WORKERS must be set in $ENV_FILE}"

echo "==> [1/9] installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
  nginx \
  certbot \
  python3-certbot-nginx \
  git \
  curl \
  ca-certificates \
  gettext-base \
  build-essential \
  libssl-dev \
  libffi-dev \
  zlib1g-dev

echo "==> [2/9] installing uv"
if ! command -v uv &>/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh \
    | env UV_INSTALL_DIR="/usr/local/bin" sh -s -- --no-modify-path
fi
command -v uv >/dev/null || {
  echo "uv install did not put a 'uv' binary on PATH (expected /usr/local/bin/uv)" >&2
  exit 1
}

echo "==> [3/9] creating $APP_USER user"
if ! id -u "$APP_USER" &>/dev/null; then
  useradd --system --create-home --home-dir "/home/$APP_USER" \
    --shell /usr/sbin/nologin "$APP_USER"
fi

# uv manages its own Python toolchain (no apt python3.x package needed)
# under APP_USER's home, so it's usable by the same user Gunicorn runs as.
sudo -u "$APP_USER" uv python install "$PYTHON_VERSION"

echo "==> [4/9] creating $APP_DIR and cloning $REPO_URL"
install -d -o "$APP_USER" -g "$APP_USER" "$APP_DIR"
if [[ ! -d "$APP_DIR/.git" ]]; then
  sudo -u "$APP_USER" git clone "$REPO_URL" "$APP_DIR"
fi
sudo -u "$APP_USER" git -C "$APP_DIR" fetch --tags
sudo -u "$APP_USER" git -C "$APP_DIR" checkout "$GIT_REF"

install -d -o "$APP_USER" -g "$APP_USER" "$APP_DIR/run"
install -d -o "$APP_USER" -g "$APP_USER" "$APP_DIR/staticfiles"

echo "==> [5/9] installing app.env to /etc/$APP_NAME/app.env"
install -d -o root -g root -m 0755 "/etc/$APP_NAME"
install -o root -g "$APP_USER" -m 0640 "$ENV_FILE" "/etc/$APP_NAME/app.env"

echo "==> [6/9] rendering and installing the Nginx site"
NGINX_VARS='${APP_NAME} ${APP_DIR} ${DOMAIN}'
envsubst "$NGINX_VARS" \
  < "$SCRIPT_DIR/templates/nginx.conf" \
  > "/etc/nginx/sites-available/$APP_NAME"
ln -sf "/etc/nginx/sites-available/$APP_NAME" "/etc/nginx/sites-enabled/$APP_NAME"
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx 2>/dev/null || systemctl restart nginx
systemctl enable nginx
# Cache the plain template rendering (pre-certbot) separately from the live
# sites-available file, which certbot edits in place to add the 443/TLS
# block. deploy.sh diffs against THIS cache, not the live file, on every
# routine deploy — otherwise it would see the live file "changed" (because
# of certbot's edits) on every single run and clobber the TLS block by
# re-rendering the plain template over it. See README.md — "Nginx and
# certbot".
install -m 0644 "/etc/nginx/sites-available/$APP_NAME" "/etc/$APP_NAME/nginx.conf.rendered"

echo "==> [7/9] rendering and installing systemd units"
GUNICORN_VARS='${APP_NAME} ${APP_USER} ${APP_DIR} ${GUNICORN_WORKERS}'
envsubst "$GUNICORN_VARS" \
  < "$SCRIPT_DIR/templates/gunicorn.service" \
  > "/etc/systemd/system/$APP_NAME.service"

IMPORT_VARS='${APP_NAME} ${APP_USER} ${APP_DIR}'
envsubst "$IMPORT_VARS" \
  < "$SCRIPT_DIR/templates/daily-import.service" \
  > "/etc/systemd/system/$APP_NAME-daily-import.service"
envsubst "$IMPORT_VARS" \
  < "$SCRIPT_DIR/templates/daily-import.timer" \
  > "/etc/systemd/system/$APP_NAME-daily-import.timer"

systemctl daemon-reload
# Gunicorn: enabled so it comes back on reboot; deploy.sh (called below)
# does the actual start via `systemctl restart`. The daily-import
# service/timer are installed only, per #16 — left disabled/unstarted for
# #17 to enable once it has settled on a schedule.
systemctl enable "$APP_NAME.service"

echo "==> [8/9] obtaining a TLS certificate for $DOMAIN"
if [[ -d "/etc/letsencrypt/live/$DOMAIN" ]]; then
  echo "certificate for $DOMAIN already present, skipping certbot"
elif [[ -z "${CERTBOT_EMAIL:-}" ]]; then
  cat >&2 <<EOF
CERTBOT_EMAIL is not set in $ENV_FILE — skipping the automatic certbot run.
Make sure DNS for $DOMAIN already points at this box, then obtain the
certificate manually (test with --staging first to avoid rate limits):
  certbot --nginx -d "$DOMAIN" --email you@example.com --agree-tos --staging
  certbot --nginx -d "$DOMAIN" --email you@example.com --agree-tos
Then re-run: sudo ./deploy.sh
EOF
else
  CERTBOT_FLAGS=(--nginx -d "$DOMAIN" --email "$CERTBOT_EMAIL" --agree-tos --non-interactive)
  if [[ "${CERTBOT_STAGING:-false}" =~ ^([1Tt]|[Yy]|true|yes)$ ]]; then
    echo "CERTBOT_STAGING is set — requesting a STAGING certificate (not trusted by browsers)."
    CERTBOT_FLAGS+=(--staging)
  fi
  certbot "${CERTBOT_FLAGS[@]}"
fi

echo "==> [9/9] handing off to deploy.sh"
exec "$SCRIPT_DIR/deploy.sh" "$ENV_FILE"
