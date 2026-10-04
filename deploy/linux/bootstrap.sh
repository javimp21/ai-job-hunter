#!/usr/bin/env bash
# One-time (and safely re-runnable) host setup for Ubuntu 24.04 (ARM64 or AMD64).
#   sudo ./deploy/linux/bootstrap.sh
# Installs Python 3.13, native PostgreSQL 16, swap (if RAM < 2 GB), unattended
# upgrades, a ufw firewall that only allows SSH, and the Europe/Madrid timezone.
# The database role/database are created from DATABASE_URL in
# $SHARED_DIR/.env (copy .env there first); the URL and password are never printed.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$here/lib/common.sh"
[ "$(id -u)" -eq 0 ] || die "run with sudo"
id "$APP_USER" >/dev/null 2>&1 || die "user $APP_USER does not exist (set APP_USER=...)"
export DEBIAN_FRONTEND=noninteractive

log "== base packages, timezone"
apt-get update -qq
apt-get install -y -qq ca-certificates curl git software-properties-common util-linux tzdata
timedatectl set-timezone "$TIMEZONE"

mem_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
log "== RAM: ${mem_mb} MB"

log "== swap"
if [ "$mem_mb" -lt 2048 ] && ! swapon --show=NAME --noheadings | grep -q .; then
    if [ ! -f /swapfile ]; then
        fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
        chmod 600 /swapfile
        mkswap /swapfile >/dev/null
    fi
    swapon /swapfile
    grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo 'vm.swappiness=10' > /etc/sysctl.d/99-ai-job-hunter-swap.conf
    sysctl -q -p /etc/sysctl.d/99-ai-job-hunter-swap.conf
    log "2 GB swapfile enabled"
else
    log "swap not needed or already present"
fi

log "== Python 3.13"
PYTHON_RECORD=/etc/ai-job-hunter/python
mkdir -p /etc/ai-job-hunter
if command -v python3.13 >/dev/null 2>&1; then
    command -v python3.13 > "$PYTHON_RECORD"
else
    # deadsnakes publishes python3.13 for noble on both amd64 and arm64.
    if add-apt-repository -y ppa:deadsnakes/ppa >/dev/null 2>&1 && apt-get update -qq \
        && apt-get install -y -qq python3.13 python3.13-venv; then
        command -v python3.13 > "$PYTHON_RECORD"
    else
        log "deadsnakes unavailable; falling back to a standalone Python from uv"
        if ! command -v uv >/dev/null 2>&1; then
            curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
        fi
        UV_PYTHON_INSTALL_DIR=/opt/python uv python install 3.13
        UV_PYTHON_INSTALL_DIR=/opt/python uv python find 3.13 > "$PYTHON_RECORD"
        chmod -R a+rX /opt/python
    fi
fi
"$(cat "$PYTHON_RECORD")" -c 'import sys, venv; assert sys.version_info[:2] == (3, 13), sys.version' \
    || die "Python 3.13 with venv is not usable"
log "Python: $(cat "$PYTHON_RECORD")"

log "== PostgreSQL 16"
apt-get install -y -qq postgresql-16 postgresql-client-16
if [ "$mem_mb" -lt 2048 ]; then sb=64MB; ec=256MB; else sb=128MB; ec=768MB; fi
conf=/etc/postgresql/16/main/conf.d/90-ai-job-hunter.conf
tmp="$(mktemp)"
cat > "$tmp" <<CONF
# Managed by deploy/linux/bootstrap.sh: small-VM memory profile.
shared_buffers = $sb
effective_cache_size = $ec
max_connections = 20
work_mem = 4MB
maintenance_work_mem = 32MB
CONF
if ! cmp -s "$tmp" "$conf" 2>/dev/null; then
    install -m 0644 -o postgres -g postgres "$tmp" "$conf"
    systemctl restart postgresql
fi
rm -f "$tmp"
systemctl enable --now postgresql >/dev/null

log "== application directories"
install -d -o "$APP_USER" -g "$APP_USER" -m 0755 "$APP_ROOT" "$RELEASES_DIR"
install -d -o "$APP_USER" -g "$APP_USER" -m 0750 "$SHARED_DIR" "$SHARED_DIR/data" "$SHARED_DIR/data/local" \
    "$SHARED_DIR/data/local/logs" "$SHARED_DIR/data/local/cover-letters" "$BACKUP_DIR" "$SHARED_DIR/private"

log "== database role and database (from DATABASE_URL in .env)"
if [ -f "$SHARED_DIR/.env" ]; then
    chown "$APP_USER:$APP_USER" "$SHARED_DIR/.env"
    chmod 600 "$SHARED_DIR/.env"
    if grep -q $'\r' "$SHARED_DIR/.env"; then
        die ".env has Windows (CRLF) line endings; run: sed -i 's/\\r\$//' $SHARED_DIR/.env"
    fi
    # SQL (including the password) goes to psql over stdin only.
    python3 "$here/lib/dburl.py" sql "$SHARED_DIR/.env" | sudo -u postgres psql -q -v ON_ERROR_STOP=1 -d postgres >/dev/null
    log "role and database ensured"
else
    log "WARNING: $SHARED_DIR/.env not found; copy it and re-run this script to create the database."
fi

log "== unattended-upgrades"
apt-get install -y -qq unattended-upgrades
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
CONF
systemctl enable --now unattended-upgrades >/dev/null 2>&1 || true

log "== firewall (SSH only)"
apt-get install -y -qq ufw
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow 22/tcp >/dev/null
ufw --force enable >/dev/null
# PostgreSQL listens on localhost only by default; nothing else is exposed.

log "== systemd units"
"$here/lib/install-units.sh" "$here/systemd"

log "bootstrap done. Next: see docs/SERVER.md (copy secrets and data, restore the database, deploy)"
