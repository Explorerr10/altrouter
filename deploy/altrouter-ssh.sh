#!/bin/bash
# altrouter-ssh — управление SSH для панели (запускается через sudo от root).
#   altrouter-ssh apply <port> <cidr|-> [yes|no]   порт, подсеть (AllowUsers), вход по паролю
#   altrouter-ssh key-add <user>          публичный ключ передаётся на stdin
#   altrouter-ssh key-list <user>         список ключей: index|fingerprint|comment
#   altrouter-ssh key-del <user> <index>
set -eu

CONF=/etc/ssh/sshd_config.d/altrouter.conf
SOCK_CONF=/etc/systemd/system/ssh.socket.d/altrouter.conf

die() { echo "altrouter-ssh: $*" >&2; exit 1; }

check_user() {
  [ -n "${1:-}" ] || die "Не указан пользователь"
  local uid
  uid=$(id -u "$1" 2>/dev/null) || die "Пользователь $1 не найден"
  [ "$1" = "root" ] || [ "$uid" -ge 1000 ] || die "Пользователь $1 недопустим"
}

home_of() { getent passwd "$1" | cut -d: -f6; }

socket_ssh() { systemctl is-enabled ssh.socket >/dev/null 2>&1; }

cmd_apply() {
  local port="$1" cidr="$2" pw="${3:-yes}" allow tmp sock_tmp=""
  case "$port" in ''|*[!0-9]*) die "Некорректный порт: $port" ;; esac
  [ "$port" -ge 1 ] && [ "$port" -le 65535 ] || die "Порт вне диапазона 1-65535"
  case "$pw" in yes|no) ;; *) die "Некорректное значение pwauth: $pw" ;; esac
  allow="*@127.0.0.0/8 *@::1/128"
  if [ "$cidr" != "-" ]; then
    python3 -c 'import ipaddress,sys; ipaddress.ip_network(sys.argv[1])' "$cidr" \
      >/dev/null 2>&1 || die "Некорректная подсеть: $cidr"
    allow="*@$cidr $allow"
  fi
  sock_old=0; socket_ssh && sock_old=1
  tmp=$(mktemp)
  printf '# Управляется панелью altrouter\nPort %s\nAllowUsers %s\nPasswordAuthentication %s\nKbdInteractiveAuthentication %s\n' \
    "$port" "$allow" "$pw" "$pw" > "$tmp"
  if [ "$sock_old" = 1 ]; then
    sock_tmp=$(mktemp)
    printf '[Socket]\nListenStream=\nListenStream=%s\n' "$port" > "$sock_tmp"
  fi
  rollback() {
    if [ -f "$CONF.bak" ]; then mv "$CONF.bak" "$CONF"; else rm -f "$CONF"; fi
    if [ -n "$sock_tmp" ]; then rm -f "$SOCK_CONF"; systemctl daemon-reload; fi
    systemctl restart ssh >/dev/null 2>&1 || true
  }
  [ -f "$CONF" ] && cp "$CONF" "$CONF.bak" || true
  install -m 644 "$tmp" "$CONF"
  if [ -n "$sock_tmp" ]; then
    mkdir -p "$(dirname "$SOCK_CONF")"
    install -m 644 "$sock_tmp" "$SOCK_CONF"
  fi
  rm -f "$tmp" "$sock_tmp"
  if ! sshd -t 2>/dev/null; then
    rollback
    die "sshd отклонил настройки, изменения отменены"
  fi
  if [ "$sock_old" = 1 ]; then
    systemctl daemon-reload
    if ! systemctl restart ssh.socket ssh >/dev/null 2>&1; then
      rollback
      die "Не удалось перезапустить ssh, изменения отменены"
    fi
  elif ! systemctl restart ssh >/dev/null 2>&1; then
    rollback
    die "Не удалось перезапустить ssh, изменения отменены"
  fi
  rm -f "$CONF.bak"
}

cmd_key_add() {
  local user="$1" key fp dir ak
  check_user "$user"
  key=$(cat)
  key="${key%$'\r'}"
  key="${key%$'\n'}"
  [ -n "$key" ] || die "Пустой ключ"
  printf '%s\n' "$key" | ssh-keygen -lf - >/dev/null 2>&1 \
    || die "Не похоже на публичный ключ OpenSSH"
  fp=$(printf '%s\n' "$key" | ssh-keygen -lf - | awk '{print $2}')
  dir="$(home_of "$user")/.ssh"
  mkdir -p "$dir"
  chmod 700 "$dir"
  ak="$dir/authorized_keys"
  touch "$ak"
  chmod 600 "$ak"
  grep -qsF "$key" "$ak" && die "Такой ключ уже добавлен"
  printf '%s\n' "$key" >> "$ak"
  chown -R "$user:" "$dir"
  echo "$fp"
}

cmd_key_list() {
  local user="$1" ak line n=0 info
  check_user "$user"
  ak="$(home_of "$user")/.ssh/authorized_keys"
  [ -f "$ak" ] || return 0
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    case "$line" in '#'*) continue ;; esac
    n=$((n + 1))
    info=$(printf '%s\n' "$line" | ssh-keygen -lf - 2>/dev/null) || info="- -"
    set -- $info
    fp=${2:--}
    shift 2 2>/dev/null || true
    printf '%s|%s|%s\n' "$n" "$fp" "$*"
  done < "$ak"
}

cmd_key_del() {
  local user="$1" idx="$2" ak tmp total
  check_user "$user"
  case "$idx" in ''|*[!0-9]*) die "Некорректный номер ключа" ;; esac
  ak="$(home_of "$user")/.ssh/authorized_keys"
  [ -f "$ak" ] || die "У пользователя нет ключей"
  total=$(awk 'NF && $1 !~ /^#/ {n++} END {print n + 0}' "$ak")
  [ "$idx" -ge 1 ] && [ "$idx" -le "$total" ] || die "Ключ №$idx не найден"
  tmp=$(mktemp)
  awk -v skip="$idx" 'NF && $1 !~ /^#/ {n++; if (n == skip) next} {print}' "$ak" > "$tmp"
  chown --reference="$ak" "$tmp"
  chmod --reference="$ak" "$tmp"
  cat "$tmp" > "$ak"
  rm -f "$tmp"
}

case "${1:-}" in
  apply)
    { [ "$#" -eq 3 ] || [ "$#" -eq 4 ]; } || die "usage: altrouter-ssh apply <port> <cidr|-> [yes|no]"
    cmd_apply "$2" "$3" "${4:-yes}"
    ;;
  key-add)
    [ "$#" -eq 2 ] || die "usage: altrouter-ssh key-add <user>"
    cmd_key_add "$2"
    ;;
  key-list)
    [ "$#" -eq 2 ] || die "usage: altrouter-ssh key-list <user>"
    cmd_key_list "$2"
    ;;
  key-del)
    [ "$#" -eq 3 ] || die "usage: altrouter-ssh key-del <user> <index>"
    cmd_key_del "$2" "$3"
    ;;
  *)
    die "usage: altrouter-ssh {apply|key-add|key-list|key-del} ..."
    ;;
esac
