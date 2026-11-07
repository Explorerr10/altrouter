#!/bin/bash
# AltRouter: полная установка и настройка backend + frontend на Debian 13 (trixie).
# Запуск на сервере: sudo bash install.sh [SRC]     (SRC по умолчанию /tmp/altrouter-deploy)
# Интерактивные вопросы задаются при запуске в терминале; иначе (deploy.ps1, cron) берутся
# из переменных ALTROUTER_PORT, ALTROUTER_BIND, ALTROUTER_MGMT_IFACE, ALTROUTER_ADMIN_USER,
# ALTROUTER_ADMIN_PASSWORD, ALTROUTER_CERT_SAN или значений по умолчанию.
set -eu

SRC="${1:-/tmp/altrouter-deploy}"
BASE=/opt/altrouter
ETC=/etc/altrouter
PKGS="sudo python3-venv python3-pip openssl curl nftables dnsmasq wireguard-tools ppp traceroute tcpdump"

die() { echo "install: ERROR: $*" >&2; exit 1; }
log() { echo "install: $*"; }

# ---------- 0. Проверки окружения и артефактов ----------
[ "$(id -u)" -eq 0 ] || die "нужен root: sudo bash $0 [SRC]"
[ -d "$SRC/backend/app" ] || die "$SRC/backend/app не найден — артефакты не переданы/не распакованы"
[ -f "$SRC/backend/requirements.txt" ] || die "$SRC/backend/requirements.txt не найден"
[ -f "$SRC/deploy/sudoers.altrouter" ] || die "$SRC/deploy/sudoers.altrouter не найден"
[ -f "$SRC/deploy/altrouter-netapply.sh" ] || die "$SRC/deploy/altrouter-netapply.sh не найден"
[ -f "$SRC/deploy/altrouter-ssh.sh" ] || die "$SRC/deploy/altrouter-ssh.sh не найден"
[ -f "$SRC/deploy/altrouter-ifstate.sh" ] || die "$SRC/deploy/altrouter-ifstate.sh не найден"
[ -f "$SRC/deploy/sysctl-altrouter.conf" ] || die "$SRC/deploy/sysctl-altrouter.conf не найден"
grep -qi debian /etc/os-release || log "WARNING: ОС не Debian — скрипт рассчитан на Debian 13"

# ---------- 1. Пошаговые настройки ----------
DEF_IP=$(hostname -I 2>/dev/null | awk '{print $1}')

PORT="${ALTROUTER_PORT:-9000}"
BIND="${ALTROUTER_BIND:-0.0.0.0}"
# mgmt задаётся только явно: автоопределение по default-route назначало
# управляющим интерфейс, через который идёт деплой (функция mgmt не задействована).
MGMT_IFACE="${ALTROUTER_MGMT_IFACE:-}"
ADMIN_USER="${ALTROUTER_ADMIN_USER:-admin}"
ADMIN_PASSWORD="${ALTROUTER_ADMIN_PASSWORD:-}"
CERT_SAN="${ALTROUTER_CERT_SAN:-$DEF_IP}"
GENERATED_PW=0

if [ -t 0 ]; then
  log "--- Настройка установки (Enter = значение по умолчанию) ---"
  while :; do
    read -r -p "Порт веб-интерфейса (HTTPS) [$PORT]: " in || in=""
    PORT="${in:-$PORT}"
    case "$PORT" in ''|*[!0-9]*) echo "  -> введите число 1024-65535"; continue ;; esac
    if [ "$PORT" -ge 1024 ] && [ "$PORT" -le 65535 ]; then break; fi
    echo "  -> введите число 1024-65535 (панель работает без root, порты ниже 1024 недоступны)"
  done
  read -r -p "Адрес привязки панели (0.0.0.0 = все интерфейсы) [$BIND]: " in || in=""
  BIND="${in:-$BIND}"
  read -r -p "Логин администратора панели [$ADMIN_USER]: " in || in=""
  ADMIN_USER="${in:-$ADMIN_USER}"
  if [ ! -f "$ETC/config.json" ]; then
    while [ -z "$ADMIN_PASSWORD" ]; do
      read -rs -p "Пароль администратора (Enter = сгенерировать): " pw1; echo
      if [ -z "$pw1" ]; then
        ADMIN_PASSWORD=$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16)
        GENERATED_PW=1
        break
      fi
      read -rs -p "Повторите пароль: " pw2; echo
      [ "$pw1" = "$pw2" ] && ADMIN_PASSWORD=$pw1 || echo "  -> пароли не совпадают, ещё раз"
    done
  fi
  read -r -p "IP/домен для HTTPS-сертификата (SAN) [${CERT_SAN:-нет}]: " in || in=""
  CERT_SAN="${in:-$CERT_SAN}"
fi

case "$PORT" in ''|*[!0-9]*) die "PORT должен быть числом: $PORT" ;; esac
[ "$PORT" -ge 1024 ] && [ "$PORT" -le 65535 ] || die "PORT вне диапазона 1024-65535: $PORT (панель работает от непривилегированного пользователя, порты ниже 1024 недоступны)"
if command -v ss >/dev/null 2>&1 && ss -tln 2>/dev/null | grep -qE ":$PORT\$"; then
  log "WARNING: порт $PORT уже занят — освободите его или выберите другой, иначе сервис не запустится"
fi
[ -n "$ADMIN_USER" ] || die "логин администратора не задан"
if [ -n "$MGMT_IFACE" ] && ! ip link show "$MGMT_IFACE" >/dev/null 2>&1; then
  log "WARNING: интерфейс $MGMT_IFACE не найден — проверьте настройки позже в панели"
fi

log "Порт: $PORT, привязка: $BIND, упр. интерфейс: ${MGMT_IFACE:-не задан}, админ: $ADMIN_USER"
if [ -z "$MGMT_IFACE" ]; then
  log "Управляющий интерфейс не задан — функция mgmt отключена (задайте ALTROUTER_MGMT_IFACE при необходимости)"
fi

# ---------- 2. Системные зависимости (чистая ОС) ----------
export DEBIAN_FRONTEND=noninteractive
missing=""
for p in $PKGS; do dpkg -s "$p" >/dev/null 2>&1 || missing="$missing $p"; done
if [ -n "$missing" ]; then
  log "apt-get install:$missing"
  apt-get update -qq
  apt-get install -y $missing >/dev/null
fi
# dnsmasq из пакета стартует с дефолтным конфигом; конфигом управляет панель
systemctl stop dnsmasq 2>/dev/null || true

# ---------- 3. Пользователь и каталоги ----------
if ! id -u altrouter >/dev/null 2>&1; then
  useradd --system --home-dir "$BASE" --shell /usr/sbin/nologin altrouter
fi
# journalctl без sudo: панель читает системный журнал через группу systemd-journal.
usermod -aG systemd-journal altrouter

mkdir -p "$ETC" "$BASE/backend" "$BASE/frontend" "$BASE/certs" "$BASE/backups"
chown altrouter:altrouter "$ETC"

# ---------- 4. Артефакты backend/frontend ----------
log "Копирование артефактов"
rm -rf "$BASE/backend/app"
cp -r "$SRC/backend/app" "$BASE/backend/app"
find "$BASE/backend/app" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
cp "$SRC/backend/requirements.txt" "$SRC/backend/pyproject.toml" "$BASE/backend/"

rm -rf "$BASE/frontend"/*
if [ -d "$SRC/frontend/dist" ]; then
  cp -r "$SRC/frontend/dist/." "$BASE/frontend/"
else
  log "WARNING: frontend/dist нет в артефактах — ставлю заглушку. Соберите UI: npm run build --prefix frontend"
  printf '<!doctype html><meta charset="utf-8"><title>AltRouter</title><p>UI не собран: npm run build --prefix frontend, затем повторите установку.\n' \
    > "$BASE/frontend/index.html"
fi

# ---------- 5. Python-окружение ----------
if [ ! -x "$BASE/venv/bin/python" ]; then
  log "Создание venv"
  python3 -m venv "$BASE/venv"
fi
log "Установка python-зависимостей"
"$BASE/venv/bin/pip" install --upgrade pip -q
"$BASE/venv/bin/pip" install -r "$BASE/backend/requirements.txt" -q

# ---------- 6. Администратор панели (только при первой установке) ----------
if [ ! -f "$ETC/config.json" ]; then
  [ -n "$ADMIN_PASSWORD" ] || ADMIN_PASSWORD=$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16)
  GENERATED_PW=1
  log "Создание администратора $ADMIN_USER"
  ADMIN_USER="$ADMIN_USER" ADMIN_PASSWORD="$ADMIN_PASSWORD" PYTHONDONTWRITEBYTECODE=1 \
    "$BASE/venv/bin/python" - <<'EOF'
import os, sys
sys.path.insert(0, "/opt/altrouter/backend")
from pathlib import Path
from app.auth.passwords import hash_password
from app.auth.users import UsersStore, User
store = UsersStore(Path("/etc/altrouter"))
users = store.load()
name, pw = os.environ["ADMIN_USER"], os.environ["ADMIN_PASSWORD"]
if any(u.username == name for u in users):
    store.set_password(name, pw)
else:
    users.append(User(name, hash_password(pw)))
    store.save(users)
EOF
  chown altrouter:altrouter "$ETC/config.json"
  chmod 600 "$ETC/config.json"
else
  log "Пользователи панели уже настроены ($ETC/config.json) — не изменяю"
fi

# ---------- 7. HTTPS-сертификат (не перезаписывать существующий) ----------
if [ ! -f "$BASE/certs/altrouter.crt" ]; then
  log "Генерация самоподписанного сертификата"
  SAN=""
  if [ -n "$CERT_SAN" ]; then
    case "$CERT_SAN" in
      *[!0-9.]*) SAN="-addext subjectAltName=DNS:$CERT_SAN" ;;
      *) SAN="-addext subjectAltName=IP:$CERT_SAN" ;;
    esac
  fi
  # shellcheck disable=SC2086
  openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
    -keyout "$BASE/certs/altrouter.key" -out "$BASE/certs/altrouter.crt" \
    -subj "/CN=altrouter" $SAN
fi
chown -R altrouter:altrouter "$BASE"
chmod 600 "$BASE/certs/altrouter.key"

# ---------- 8. sudoers, helper-скрипты, sysctl ----------
visudo -cf "$SRC/deploy/sudoers.altrouter" >/dev/null
install -m 440 -o root -g root "$SRC/deploy/sudoers.altrouter" /etc/sudoers.d/altrouter
install -m 755 -o root -g root "$SRC/deploy/altrouter-netapply.sh" /usr/local/sbin/altrouter-netapply
install -m 755 -o root -g root "$SRC/deploy/altrouter-ssh.sh" /usr/local/sbin/altrouter-ssh
install -m 755 -o root -g root "$SRC/deploy/altrouter-ifstate.sh" /usr/local/sbin/altrouter-ifstate
# IP-форвардинг обязателен для NAT/маршрутизации сегментов; sysctl.d — персистентно.
install -m 644 -o root -g root "$SRC/deploy/sysctl-altrouter.conf" /etc/sysctl.d/90-altrouter.conf
sysctl -p /etc/sysctl.d/90-altrouter.conf >/dev/null

# ---------- 9. systemd-юнит (порт/адрес из настроек) ----------
log "Установка systemd-юнита (порт $PORT)"
MGMT_ENV=""
if [ -n "$MGMT_IFACE" ]; then MGMT_ENV="Environment=ALTROUTER_MGMT_IFACE=$MGMT_IFACE"; fi
cat > /etc/systemd/system/altrouter.service <<EOF
[Unit]
Description=AltRouter web panel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=altrouter
Group=altrouter
WorkingDirectory=$BASE/backend
Environment=ALTROUTER_STATIC_DIR=$BASE/frontend
$MGMT_ENV
ExecStart=$BASE/venv/bin/uvicorn app.main:app --host $BIND --port $PORT --ssl-certfile $BASE/certs/altrouter.crt --ssl-keyfile $BASE/certs/altrouter.key
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable altrouter >/dev/null
# nftables и dnsmasq грузятся при загрузке; конфиги ставит altrouter-netapply.
systemctl enable nftables dnsmasq >/dev/null 2>&1 || true
systemctl restart altrouter
sleep 2
systemctl --no-pager -l status altrouter | head -8 || true

# ---------- 10. Health-check и итог ----------
HEALTH=""
if curl -sk --max-time 10 "https://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
  HEALTH="ok"
  log "Установка завершена (health ok)"
else
  log "WARNING: health-check не прошёл — journalctl -u altrouter"
fi
log "Панель: https://${DEF_IP:-<ip-сервера>}:$PORT (логин: $ADMIN_USER)"
if [ "$GENERATED_PW" -eq 1 ]; then
  log "Пароль администратора (сохраните, больше не показывается): $ADMIN_PASSWORD"
fi
[ "$HEALTH" = "ok" ]
