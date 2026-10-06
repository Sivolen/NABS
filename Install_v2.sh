#!/usr/bin/env bash
#
# NABS installer and updater. Safe to run again on an existing installation:
#   * config.py (the secrets, the DB settings) is created ONCE and never overwritten -
#     a new CREDENTIALS_ENCRYPTION_KEY would make every saved SSH password unreadable;
#   * the database and its data are never dropped or recreated;
#   * an nginx site and a systemd unit that you have changed are kept.
#
#   ./Install_v2.sh                  production: expects certs/cert.pem and certs/key.pem
#   ./Install_v2.sh --self-signed    TEST installation: creates a self-signed certificate
#   ./Install_v2.sh --skip-nginx     do not touch nginx (you publish the application yourself)
#
# The settings live in the Python module config.py (made from config_example.py);
# there is no YAML configuration.
#
# Optional environment: NABS_APP_DIR (default: the directory of this script),
# NABS_SERVICE_USER (default: nabs). The other NABS_* variables are test hooks.

set -euo pipefail

SELF_SIGNED=0
SKIP_NGINX=0
for argument in "$@"; do
    case "$argument" in
        --self-signed) SELF_SIGNED=1 ;;
        --skip-nginx) SKIP_NGINX=1 ;;
        -h | --help) sed -n '2,16p' "$0"; exit 0 ;;
        *) echo "Unknown option: $argument (see --help)" >&2; exit 2 ;;
    esac
done

APP_DIR="${NABS_APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
SERVICE_USER="${NABS_SERVICE_USER:-nabs}"
SERVICE_GROUP="${NABS_SERVICE_GROUP:-$SERVICE_USER}"
SYSTEMD_DIR="${NABS_SYSTEMD_DIR:-/etc/systemd/system}"
NGINX_DIR="${NABS_NGINX_DIR:-/etc/nginx}"
CERT_FILE="$APP_DIR/certs/cert.pem"
KEY_FILE="$APP_DIR/certs/key.pem"

log() { echo "[$1] $2"; }
die() { echo "ERROR: $*" >&2; exit 1; }
# run with root rights (directly when we are root already)
priv() { if [[ $EUID -eq 0 ]]; then "$@"; else sudo "$@"; fi; }
# run as the unprivileged service user
as_service_user() {
    if [[ $EUID -eq 0 ]]; then runuser -u "$SERVICE_USER" -- "$@"; else sudo -u "$SERVICE_USER" "$@"; fi
}

[[ -f "$APP_DIR/config_example.py" && -f "$APP_DIR/scripts/nabs_setup.py" ]] ||
    die "$APP_DIR does not look like a NABS directory (config_example.py / scripts/ not found)"
cd "$APP_DIR"

# ---------------------------------------------------------------- 0. pre-flight checks
# Everything that can be checked before the first change is checked here, so a problem
# does not leave a half-installed system.
if [[ $SKIP_NGINX -eq 0 ]]; then
    if [[ -f "$CERT_FILE" && -f "$KEY_FILE" ]]; then
        :
    elif [[ -e "$CERT_FILE" || -e "$KEY_FILE" ]]; then
        die "Only one of $CERT_FILE and $KEY_FILE exists. Provide both, or remove the broken one."
    elif [[ $SELF_SIGNED -eq 0 ]]; then
        die "No certificate: $CERT_FILE and $KEY_FILE are missing. Put your certificate and key there, run with --self-signed for a test installation, or with --skip-nginx."
    fi
fi

# ------------------------------------------------------------ 1. system packages
if [[ "${NABS_SKIP_PACKAGES:-0}" != 1 ]]; then
    log "1/11" "Installing system packages..."
    priv apt-get update
    priv apt-get install -y python3 python3-venv python3-pip postgresql git nginx openssl
else
    log "1/11" "Skipping system packages (NABS_SKIP_PACKAGES=1)"
fi

# ------------------------------------------------------- 2. the service user (no root)
log "2/11" "Service user '$SERVICE_USER'..."
if id -u "$SERVICE_USER" > /dev/null 2>&1; then
    echo "    exists"
else
    priv useradd --system --user-group --no-create-home --home-dir "$APP_DIR" \
        --shell /usr/sbin/nologin "$SERVICE_USER"
fi

# ------------------------------------------------------- 3. Python environment
if [[ "${NABS_SKIP_VENV:-0}" != 1 ]]; then
    log "3/11" "Python virtual environment and packages..."
    [[ -d venv ]] || python3 -m venv venv
    venv/bin/pip install --upgrade pip
    venv/bin/pip install -r requirements.txt
else
    log "3/11" "Skipping the virtual environment (NABS_SKIP_VENV=1)"
fi
if [[ -n "${NABS_PYTHON:-}" ]]; then PYTHON="$NABS_PYTHON"
elif [[ -x venv/bin/python ]]; then PYTHON="$APP_DIR/venv/bin/python"
else PYTHON=python3; fi
FLASK="${NABS_FLASK:-$APP_DIR/venv/bin/flask}"

if [[ -n "${NABS_PSQL:-}" ]]; then PSQL_COMMAND="$NABS_PSQL"
elif [[ $EUID -eq 0 ]]; then PSQL_COMMAND="runuser -u postgres -- psql"
else PSQL_COMMAND="sudo -u postgres psql"; fi

if [[ -n "${NABS_HELPER:-}" ]]; then
    # shellcheck disable=SC2206
    HELPER=($NABS_HELPER)
else
    HELPER=("$PYTHON" "$APP_DIR/scripts/nabs_setup.py" --app-dir "$APP_DIR"
        --service-user "$SERVICE_USER" --service-group "$SERVICE_GROUP" --psql "$PSQL_COMMAND")
fi
helper() { "${HELPER[@]}" "$@"; }

# ------------------------------------------------------- 4. configuration (config.py)
log "4/11" "Configuration (config.py)..."
set +e
helper init-config
init_status=$?
set -e
case $init_status in
    0) echo "    A new config.py was created. BACK IT UP: it holds CREDENTIALS_ENCRYPTION_KEY - without that key the saved SSH passwords cannot be read." ;;
    3) echo "    The existing config.py is kept unchanged (secrets and DB settings are not touched)." ;;
    *) die "Could not prepare config.py" ;;
esac
helper check-config || die "Fix config.py (see above) and run the installer again. Do NOT generate a new CREDENTIALS_ENCRYPTION_KEY if passwords are already saved: put the original one back."

# ------------------------------------------------------- 5. PostgreSQL
log "5/11" "PostgreSQL database and user (names and password come from config.py)..."
if [[ "${NABS_SKIP_PACKAGES:-0}" != 1 ]]; then
    priv systemctl start postgresql || true
fi
helper provision-db || die "Could not create the database or the user"

# ------------------------------------------------------- 6. directories and rights
log "6/11" "Directories and access rights (no chmod 777)..."
mkdir -p logs backups user_uploads certs
priv chgrp "$SERVICE_GROUP" config.py
priv chmod 640 config.py
priv chown -R "$SERVICE_USER:$SERVICE_GROUP" logs backups user_uploads
priv chmod 750 logs backups user_uploads
chmod 750 certs

# ------------------------------------------------------- 7. certificate
if [[ $SKIP_NGINX -eq 0 ]]; then
    if [[ ! -f "$CERT_FILE" && $SELF_SIGNED -eq 1 ]]; then
        log "7/11" "Creating a SELF-SIGNED certificate (test mode, --self-signed)..."
        openssl req -new -newkey rsa:4096 -days 365 -nodes -x509 \
            -keyout "$KEY_FILE" -out "$CERT_FILE" \
            -subj "/C=RU/ST=RU/L=City/O=NABS/OU=IT/CN=localhost"
    else
        log "7/11" "Using the existing certificate $CERT_FILE"
    fi
    chmod 600 "$KEY_FILE"
    chmod 644 "$CERT_FILE"
else
    log "7/11" "Skipping the certificate (--skip-nginx)"
fi

# ------------------------------------------------------- 8. can the service user work?
log "8/11" "Checking the rights of '$SERVICE_USER'..."
as_service_user test -r "$APP_DIR/config.py" ||
    die "$SERVICE_USER cannot read $APP_DIR/config.py (the directory must be traversable: check the rights of every parent directory, e.g. a home directory is usually closed)"
as_service_user test -w "$APP_DIR/logs" || die "$SERVICE_USER cannot write to $APP_DIR/logs"
as_service_user test -r "$APP_DIR/supervisor/config_gunicorn.py" ||
    die "$SERVICE_USER cannot read the application files in $APP_DIR"

# ------------------------------------------------------- 9. database schema
log "9/11" "Database connection and schema..."
helper db-check || die "The database is not usable with the settings of config.py"
export FLASK_APP=app
# Widens credentials_password to TEXT on an existing database (idempotent, never touches
# the stored values). On a new database the table does not exist yet: nothing to do.
if [[ -n "${NABS_MIGRATE_TEXT_CMD:-}" ]]; then
    # shellcheck disable=SC2086
    $NABS_MIGRATE_TEXT_CMD
else
    "$PYTHON" scripts/migrate_credentials_password_text.py --apply
fi
if [[ -d migrations ]]; then
    "$FLASK" db upgrade                       # an existing database: bring it to the latest revision first
    "$FLASK" db migrate -m "NABS update $(date +%F)"
    "$FLASK" db upgrade
else
    "$FLASK" db init
    "$FLASK" db migrate -m "Initial migration"
    "$FLASK" db upgrade
fi

# ------------------------------------------------------- 10. services
log "10/11" "systemd services..."
for unit in nabs nabs-scheduler; do
    target="$SYSTEMD_DIR/$unit.service"
    rendered="$(mktemp)"
    helper render "$APP_DIR/supervisor/$unit.service" > "$rendered"
    if [[ ! -f "$target" ]]; then
        priv install -m 644 "$rendered" "$target"
        echo "    installed $unit.service"
    elif grep -q '^User=root' "$target" || ! grep -q '^User=' "$target"; then
        # the old default ran as root: replace it (a copy is kept)
        priv cp -p "$target" "$target.bak-$(date +%Y%m%d%H%M%S)"
        priv install -m 644 "$rendered" "$target"
        echo "    $unit.service ran as root: replaced, the old file is saved next to it"
    else
        echo "    $unit.service has its own User= setting: kept as it is"
    fi
    rm -f "$rendered"
done
priv systemctl daemon-reload
priv systemctl enable nabs nabs-scheduler
priv systemctl restart nabs nabs-scheduler
for unit in nabs nabs-scheduler; do
    started=0
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        if priv systemctl is-active --quiet "$unit"; then started=1; break; fi
        sleep 1
    done
    if [[ $started -eq 0 ]]; then
        priv journalctl -u "$unit" -n 30 --no-pager || true
        die "$unit did not start (see the log above)"
    fi
done

# ------------------------------------------------------- 11. nginx
if [[ $SKIP_NGINX -eq 0 ]]; then
    log "11/11" "nginx..."
    site="$NGINX_DIR/sites-available/nabs"
    enabled="$NGINX_DIR/sites-enabled/nabs"
    created_site=0
    if [[ -f "$site" ]]; then
        echo "    $site exists: kept as it is"
    else
        rendered="$(mktemp)"
        helper render "$APP_DIR/supervisor/nabs" > "$rendered"
        priv install -m 644 "$rendered" "$site"
        rm -f "$rendered"
        priv rm -f "$NGINX_DIR/sites-enabled/default"
        created_site=1
    fi
    priv ln -sf "$site" "$enabled"
    if ! priv nginx -t; then
        if [[ $created_site -eq 1 ]]; then priv rm -f "$enabled"; fi
        die "nginx -t failed: nginx was NOT reloaded"
    fi
    priv systemctl reload nginx || priv systemctl restart nginx
else
    log "11/11" "Skipping nginx (--skip-nginx)"
fi

echo ""
echo "=== NABS is installed: https://localhost (the application listens on 127.0.0.1:8000) ==="
if [[ $SELF_SIGNED -eq 1 ]]; then echo "The certificate is self-signed: confirm it in the browser."; fi
echo ""
echo "First installation only - the default admin (admin@admin.local) was created on the first start;"
echo "its random password was written ONCE to the service log:"
echo "  journalctl -u nabs --since \"5 minutes ago\" | grep -A 5 'Default admin user created'"
echo "Log in and change it. More users: python3 create_user.py -a <email>"
echo ""
echo "Keep a copy of config.py (CREDENTIALS_ENCRYPTION_KEY) in a safe place."
