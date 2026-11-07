#!/bin/bash
# AltRouter: установка сгенерированных конфигов (networkd, dnsmasq, nftables).
# Вызывается панелью через sudo (белый список sudoers.altrouter).
# Аргументов нет: источник фиксирован и принадлежит пользователю altrouter.
# Файлы с префиксом altrouter- в /etc/systemd/network управляются только панелью.

set -eu

STAGING=/etc/altrouter/network/staging
NETD=/etc/systemd/network
DNSMASQ_CONF=/etc/dnsmasq.conf
DNSMASQ_ORIG=/etc/dnsmasq.conf.altrouter-orig
NFT_CONF=/etc/nftables.conf

mkdir -p "$NETD"

find "$NETD" -maxdepth 1 -type f \( -name 'altrouter-*.network' -o -name 'altrouter-*.netdev' \) -delete

if [ -d "$STAGING" ]; then
  for f in "$STAGING"/*.network "$STAGING"/*.netdev; do
    [ -e "$f" ] || continue
    # WireGuard-netdev содержит приватный ключ — 640 root:systemd-network:
    # networkd читает файлы от пользователя systemd-network, 600 root:root
    # вызывают «Permission denied» и туннель не создаётся.
    case "$f" in
      *arwg-*.netdev) mode=640; group=systemd-network ;;
      *) mode=644; group=root ;;
    esac
    install -m "$mode" -o root -g "$group" "$f" "$NETD/$(basename "$f")"
  done
fi

# PPPoE: peers-файлы (содержат пароль — 600) и юниты pppd ставятся только из staging.
PEERS=/etc/ppp/peers
if [ -d "$STAGING" ]; then
  for f in "$STAGING"/altrouter-ppp-*.peers; do
    [ -e "$f" ] || continue
    mkdir -p "$PEERS"
    install -m 600 -o root -g root "$f" "$PEERS/$(basename "$f" .peers)"
  done
  for f in "$STAGING"/altrouter-ppp-*.service; do
    [ -e "$f" ] || continue
    install -m 644 -o root -g root "$f" /etc/systemd/system/"$(basename "$f")"
  done
fi

for f in "$PEERS"/altrouter-*; do
  [ -e "$f" ] || continue
  [ -f "$STAGING/$(basename "$f").peers" ] || rm -f "$f"
done
for f in /etc/systemd/system/altrouter-ppp-*.service; do
  [ -e "$f" ] || continue
  if [ ! -f "$STAGING/$(basename "$f")" ]; then
    systemctl stop "${f##*/}" >/dev/null 2>&1 || true
    systemctl disable "${f##*/}" >/dev/null 2>&1 || true
    systemctl reset-failed "${f##*/}" >/dev/null 2>&1 || true
    rm -f "$f"
  fi
done

RESTART_DNSMASQ=no

# В Debian conf-dir=/etc/dnsmasq.d закомментирован в дистрибутивном конфиге,
# поэтому панель ставит свой конфиг прямо в /etc/dnsmasq.conf.
# Оригинал сохраняется при первой установке для симметричного отката.
if [ -f "$STAGING/dnsmasq.conf" ]; then
  [ -f "$DNSMASQ_ORIG" ] || cp -a /etc/dnsmasq.conf "$DNSMASQ_ORIG"
  install -m 644 -o root -g root "$STAGING/dnsmasq.conf" "$DNSMASQ_CONF"
  dnsmasq --test -C "$DNSMASQ_CONF" >/dev/null
  RESTART_DNSMASQ=yes
elif [ -f "$DNSMASQ_ORIG" ]; then
  install -m 644 -o root -g root "$DNSMASQ_ORIG" "$DNSMASQ_CONF"
  RESTART_DNSMASQ=yes
fi

if [ -f "$STAGING/nftables.conf" ]; then
  install -m 644 -o root -g root "$STAGING/nftables.conf" "$NFT_CONF"
  nft -c -f "$NFT_CONF"
fi

# set -eu: любая неудача откатывает транзакцию в панели. Быстрые применения подряд
# могут столкнуться с незавершённым systemd-job (networkctl/systemctl) — поэтому
# эти два шага с коротким ретраем.
retry() {
  local n=1
  until "$@"; do
    n=$((n + 1))
    if [ "$n" -gt 3 ]; then
      return 1
    fi
    sleep 1
  done
}

# Мосты сегментов должны появиться до старта dnsmasq (interface=) — сначала networkd.
retry networkctl reload

# networkd не удаляет kernel-устройство при удалении .netdev — подчищаем осиротевшие мосты.
for net in /sys/class/net/arbr-*; do
  [ -e "$net" ] || continue
  br=${net##*/}
  if [ ! -f "$NETD/altrouter-$br.netdev" ]; then
    ip link delete "$br" >/dev/null 2>&1 || true
  fi
done

# PPPoE-сессии стартуют после networkd: физический порт должен быть поднят.
systemctl daemon-reload
for f in "$STAGING"/altrouter-ppp-*.service; do
  [ -e "$f" ] || continue
  unit=${f##*/}
  retry systemctl enable "$unit" >/dev/null
  retry systemctl restart "$unit"
done

if [ -f "$NFT_CONF" ]; then
  nft -f "$NFT_CONF"
fi

if [ "$RESTART_DNSMASQ" = yes ]; then
  retry systemctl restart dnsmasq
fi
