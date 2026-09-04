#!/usr/bin/env bash
# deploy/smoke.sh — post-deploy health check. Runnable standalone.
#
# Asserts GET https://$DOMAIN/accounts/login/ returns 200.
#
# Usage:
#   ./smoke.sh example.com                # domain as an argument
#   DOMAIN=example.com ./smoke.sh          # or as an env var
#   ./smoke.sh                             # or sourced from app.env, if run
#                                           # from deploy/ next to a filled-in
#                                           # app.env (or /etc/<APP_NAME>/app.env)
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"

DOMAIN="${1:-${DOMAIN:-}}"
if [[ -z "$DOMAIN" ]]; then
  for candidate in "$SCRIPT_DIR/app.env" /etc/*/app.env; do
    if [[ -f "$candidate" ]]; then
      # shellcheck disable=SC1090
      DOMAIN="$(set -a; source "$candidate"; set +a; echo "$DOMAIN")"
      break
    fi
  done
fi
if [[ -z "$DOMAIN" ]]; then
  echo "usage: smoke.sh <domain>   (or set DOMAIN=, or run next to app.env)" >&2
  exit 1
fi

URL="https://$DOMAIN/accounts/login/"
CODE="$(curl -fsS -o /dev/null -w '%{http_code}' "$URL" || true)"

if [[ "$CODE" != "200" ]]; then
  echo "smoke test FAILED: GET $URL -> ${CODE:-no response}" >&2
  exit 1
fi

echo "smoke test OK: GET $URL -> 200"
