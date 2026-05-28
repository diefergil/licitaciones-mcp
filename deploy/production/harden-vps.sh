#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

install -m 0644 sshd-licitaciones-hardening.conf \
  /etc/ssh/sshd_config.d/01-licitaciones-hardening.conf
rm -f /etc/ssh/sshd_config.d/99-licitaciones-hardening.conf

sshd -t
systemctl reload ssh

ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw status verbose
