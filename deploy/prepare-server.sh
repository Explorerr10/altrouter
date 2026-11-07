#!/bin/bash
set -eu

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y python3-venv dnsmasq wireguard-tools openssl curl
systemctl stop dnsmasq 2>/dev/null || true
systemctl disable dnsmasq 2>/dev/null || true
echo "prepare-server: done"
