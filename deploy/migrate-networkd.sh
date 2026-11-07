#!/bin/bash
set -eu

IFACE=enp9s0f0
MGMT_IP=192.168.1.1
ROLLBACK_SEC=300

ROLLBACK_CMD='systemctl unmask NetworkManager.service; systemctl enable --now NetworkManager.service; systemctl disable --now systemd-networkd.service systemd-networkd.socket 2>/dev/null; systemctl mask systemd-networkd.service systemd-networkd.socket'

systemd-run --unit=netd-rollback --on-active="${ROLLBACK_SEC}" /bin/sh -c "${ROLLBACK_CMD}"

cat > /etc/systemd/network/10-altrouter.network <<EOF
[Match]
Name=${IFACE}

[Network]
DHCP=yes

[DHCPv4]
ClientIdentifier=mac
RouteMetric=100
EOF
chmod 644 /etc/systemd/network/10-altrouter.network

systemctl unmask systemd-networkd.service systemd-networkd.socket
systemctl enable systemd-networkd.service
systemctl mask NetworkManager.service
systemctl stop NetworkManager.service
systemctl restart systemd-networkd.service

for i in $(seq 1 12); do
  sleep 5
  if ip -4 addr show "${IFACE}" | grep -q "inet ${MGMT_IP}/"; then
    systemctl stop netd-rollback.timer 2>/dev/null || true
    logger -t netd-migrate "success: ${MGMT_IP} acquired via systemd-networkd"
    echo "MIGRATION_OK: ${MGMT_IP}"
    exit 0
  fi
done

logger -t netd-migrate "failed: ${MGMT_IP} not acquired, rolling back"
systemctl stop netd-rollback.timer 2>/dev/null || true
/bin/sh -c "${ROLLBACK_CMD}"
echo "MIGRATION_FAILED_ROLLED_BACK"
exit 1
