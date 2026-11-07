#!/bin/bash
# AltRouter: up/down физического интерфейса (аналог `ip link set dev X up|down`).
# Вызывается панелью через sudo (белый список sudoers.altrouter).

set -eu

usage() { echo "usage: altrouter-ifstate up|down <iface>" >&2; exit 2; }

[ "$#" -eq 2 ] || usage

ACTION=$1
IFACE=$2

case "$ACTION" in
  up | down) ;;
  *) usage ;;
esac

case "$IFACE" in
  *[!A-Za-z0-9._-]* | "") usage ;;
esac

[ -d "/sys/class/net/$IFACE" ] || { echo "interface not found: $IFACE" >&2; exit 1; }

exec /usr/sbin/ip link set dev "$IFACE" "$ACTION"
