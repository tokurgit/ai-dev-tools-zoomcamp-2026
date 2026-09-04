# Deploy

A templated-shell playbook for a single Ubuntu 24.04 VPS: Nginx + Gunicorn +
systemd, TLS via Let's Encrypt, SQLite on disk. No Ansible, no containers —
those come later if this project outgrows a single box. See issue #16.

Every project-specific value lives in `app.env`. Nothing in `bootstrap.sh`,
`deploy.sh`, `smoke.sh` or `templates/*` hardcodes a project name, path or
domain, so this whole `deploy/` folder can be copied into another Django
project and reused by filling in a new `app.env` — see "Adapting to another
Django project" below.

## Layout

```
deploy/
  README.md              this file
  app.env.example         every variable, documented — copy to app.env
  bootstrap.sh            fresh-box / recovery only, run once as root
  deploy.sh               every release, safe to re-run
  smoke.sh                post-deploy health check, runnable standalone
  templates/
    nginx.conf             reverse proxy + static files
    gunicorn.service        the app server
    daily-import.service    run_daily_import, installed but not enabled (#17)
    daily-import.timer      its schedule, installed but not enabled (#17)
```

## First-time setup

1. **DNS first.** Point an A (and AAAA, if you have IPv6) record for your
   domain at the box's IP. Certbot needs this to already be live — do it
   before step 3.
2. `cp app.env.example app.env` and fill in every value (see the comments in
   the file). `app.env` is git-ignored — it holds real secrets and is never
   committed.
3. Copy `deploy/` (or the whole repo, plus `app.env`) to the box, then, as
   root:
   ```bash
   sudo ./bootstrap.sh
   ```
   This installs everything (Nginx, certbot, uv, the systemd units), obtains
   a certificate (if `CERTBOT_EMAIL` is set — otherwise it prints the manual
   command and stops there so you can DNS-check first), and ends by running
   `deploy.sh` for you.
4. Create the first admin login:
   ```bash
   cd "$APP_DIR" && sudo -u "$APP_USER" uv run python manage.py createsuperuser
   ```
5. Verify: `./smoke.sh $DOMAIN` (or just re-run `deploy.sh`, which runs it for
   you), `systemctl status <APP_NAME>` and `systemctl status nginx`, and load
   `https://$DOMAIN/admin/` in a browser.
6. **Trigger the daily import once by hand** to confirm it actually works
   before waiting for the schedule (issue #17):
   ```bash
   sudo systemctl start <APP_NAME>-daily-import.service
   journalctl -u <APP_NAME>-daily-import -n 50
   ```
   A healthy run shows the pipeline summary lines from #10 (rows parsed,
   listings created/updated, notifications queued, emails sent) and the unit
   ends `inactive (dead)` with result `success`
   (`systemctl status <APP_NAME>-daily-import.service`). `systemctl
   list-timers` shows the timer's next scheduled fire.

Test with a **staging** certificate first if you're unsure DNS/Nginx is right
— set `CERTBOT_STAGING=true` in `app.env` before the first `bootstrap.sh` run
(staging certs aren't trusted by browsers but aren't rate-limited either),
then unset it and re-run `bootstrap.sh` for the real certificate once
everything else checks out.

## Idempotency and failure behaviour

- **`bootstrap.sh` is fresh-box / recovery only.** Every step is guarded (`id
  -u` before `useradd`, `test -d .git` before `git clone`, a certificate
  presence check before calling certbot, …) so re-running it after a
  mid-way failure mostly just skips what's already done and continues. It's
  not what you run for routine releases — that's `deploy.sh`.
- **`deploy.sh` is safe to re-run.** It's the day-to-day release command:
  `git fetch` + checkout `GIT_REF`, `uv sync --frozen`, migrate,
  collectstatic, restart Gunicorn, smoke-test.
- **A failed deploy doesn't take the site down.** `deploy.sh` uses
  `systemctl restart` (never stop-then-start), and if the smoke test at the
  end fails, the script exits non-zero but does **not** try to undo the
  restart — `Restart=on-failure` in `gunicorn.service` keeps retrying the
  process that's there. To actually roll back: set `GIT_REF` in `app.env`
  back to the previous tag/SHA and re-run `deploy.sh`.

## The daily import (issue #17)

`bootstrap.sh` installs and `enable --now`s `<APP_NAME>-daily-import.timer`,
which fires `<APP_NAME>-daily-import.service` (`Type=oneshot`, running
`run_daily_import`, #10) once a day at `IMPORT_SCHEDULE` (default `07:00`,
Europe/Riga — the timer's `OnCalendar=` carries an explicit `Europe/Riga`
suffix, so this stays correct across DST with no `TZ=` juggling needed).

- **Logs.** stdout/stderr go to journald under the unit — no logfile, no
  logrotate config.
  ```bash
  journalctl -u <APP_NAME>-daily-import -n 100        # last 100 lines
  journalctl -u <APP_NAME>-daily-import --since today  # today's runs
  ```
- **Retention.** journald's own defaults already cap total log size (see
  `journalctl --disk-usage`; tune with `SystemMaxUse=` in
  `/etc/systemd/journald.conf` if you ever need to). No project-specific
  logrotate setup is needed.
- **Overlap.** The timer uses `OnCalendar` (not `OnUnitActiveSec`) and the
  service is `Type=oneshot`, so systemd never stacks two runs: if a run is
  somehow still active when the timer next fires, that trigger is simply not
  queued — the next run just happens whenever the timer fires *after* the
  current one finishes, potentially skipping that day's slot rather than
  running concurrently.
- **Failure surfacing.** `run_daily_import` (#10) exits non-zero on a fatal
  pipeline error or any failed email, so a bad run shows up as `systemctl
  status <APP_NAME>-daily-import.service` -> `failed`, with the exit code and
  full output in the journal. There's no push alert on failure — an
  `OnFailure=` hook is documented as an extension point in
  `templates/daily-import.service` but not built; wire one up (email,
  Telegram, Healthchecks.io, …) if silent failures become a problem.
- **Manual trigger.** `sudo systemctl start <APP_NAME>-daily-import.service`
  runs it on demand, any time — same command as the first-deploy check above.
- **`izsoles.csv` on the VPS.** By default (`IMPORT_FETCH=false`) the command
  only reads the local file at `IZSOLES_CSV_PATH` — an operator (or a
  separate process) is responsible for putting it there. Setting
  `IMPORT_FETCH=true` adds `--fetch`, which tries #4's `httpx` fetcher first;
  the open-data feed is known to 403 plain clients (see #4's grooming notes)
  and **whether it works from a given VPS's IP was never verified against a
  real box in this session** — test it (`IMPORT_FETCH=true`, re-run
  `bootstrap.sh`, trigger a manual run, check the log) before relying on it,
  and fall back to `IMPORT_FETCH=false` + an operator dropping the file if it
  still 403s.

## Nginx and certbot

`bootstrap.sh` renders `templates/nginx.conf` (HTTP only) once and installs
it. `certbot --nginx -d "$DOMAIN"` then edits the **installed** file in place
to add the HTTPS server block and the 80→443 redirect — that edit is never
part of the template.

`deploy.sh` also knows how to re-render and reload Nginx if the template (or
`APP_NAME`/`APP_DIR`/`DOMAIN` in `app.env`) genuinely changes, but it diffs
against a private cache (`/etc/<APP_NAME>/nginx.conf.rendered`, saved by
`bootstrap.sh`) rather than the live, certbot-edited file — otherwise every
routine deploy would see the live file as "changed" (because of certbot's own
edits) and silently overwrite the TLS block. In the rare case `deploy.sh`
*does* detect a real template change and reloads Nginx, it prints a reminder
to re-run `certbot --nginx -d "$DOMAIN"` afterward to restore the HTTPS
block.

## Adapting to another Django project

1. Copy `deploy/` into the new repo.
2. Fill in a new `app.env` (`APP_NAME`, `APP_DIR`, `DOMAIN`, `REPO_URL`, …).
3. Make sure the target project reads its settings from the environment the
   same way this one does (`config/settings.py`, issue #22) — `DJANGO_*`
   variables, no hardcoded secret/host/debug values. If it already follows
   that pattern, nothing else changes.
4. `sudo ./bootstrap.sh`.

## Notes

- **Database.** SQLite at `DJANGO_DB_PATH` (defaults to `$APP_DIR/db.sqlite3`
  if left unset). There's no automated off-box backup here — this project's
  scope doc calls for Hetzner's automated VPS snapshots to cover the DB file,
  not a dedicated backup job. If you set `DJANGO_DB_PATH` to somewhere
  outside `APP_DIR`, it survives a `git clean` of the checkout too.
- **`izsoles.csv`.** The daily importer (#4/#5, wired up by `run_daily_import`,
  #10) expects the CSV at `IZSOLES_CSV_PATH` (defaults to
  `$APP_DIR/data/izsoles.csv`). An operator drops the file there, or the
  command's `--fetch` flag tries the open-data URL itself (best-effort — see
  #4's notes on that feed's bot detection).
- **Rolling back.** Set `GIT_REF` in `app.env` to the previous tag or commit
  SHA and re-run `deploy.sh`. There is no automatic rollback-on-smoke-failure
  (see "Idempotency and failure behaviour" above) — a bad release needs a
  human to point `GIT_REF` back and redeploy.
- **The daily-import timer.** See "The daily import (issue #17)" above —
  `bootstrap.sh` installs and enables it automatically.
