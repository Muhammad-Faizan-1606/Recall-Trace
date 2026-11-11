#!/usr/bin/env bash
# One-time setup of the RecallTrace malware scanner on an Ubuntu 24.04 VM.
#
#   curl -fsSL https://raw.githubusercontent.com/Muhammad-Faizan-1606/Recall-Trace/main/operations/scanner/setup.sh \
#     | sudo bash -s -- your-name.centralindia.cloudapp.azure.com
#
# Installs ClamAV (with daily signature updates), the scanning service and Caddy for
# automatic HTTPS. Safe to run again. Prints the endpoint and a newly generated token
# once at the end: copy both into the GitHub secrets SCANNER_ENDPOINT and SCANNER_TOKEN.
set -euo pipefail

DOMAIN="${1:-}"
if [[ -z "$DOMAIN" || "$DOMAIN" == *"/"* ]]; then
  echo "Usage: setup.sh <vm-dns-name>, for example recalltrace-scan.centralindia.cloudapp.azure.com" >&2
  exit 1
fi
if [[ "$(id -u)" != "0" ]]; then
  echo "Run as root (with sudo)." >&2
  exit 1
fi
SOURCE="https://raw.githubusercontent.com/Muhammad-Faizan-1606/Recall-Trace/main/operations/scanner"
APP_DIR=/opt/recalltrace-scanner
ENV_FILE=/etc/recalltrace-scanner.env

echo "==> Swap space (ClamAV needs about 1.2 GB of memory for its signatures)"
if ! swapon --show | grep -q .; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q "^/swapfile" /etc/fstab || echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

echo "==> Packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q clamav clamav-daemon caddy python3 curl openssl >/dev/null

echo "==> ClamAV settings"
CONF=/etc/clamav/clamd.conf
set_clamd() {
  if grep -q "^$1 " "$CONF"; then sed -i "s|^$1 .*|$1 $2|" "$CONF"; else echo "$1 $2" >> "$CONF"; fi
}
set_clamd StreamMaxLength 12M
set_clamd MaxFileSize 12M
set_clamd MaxScanSize 48M
# Reload signatures in place so memory does not double during daily updates.
set_clamd ConcurrentDatabaseReload no

echo "==> Virus signatures (first download takes a few minutes)"
systemctl stop clamav-freshclam || true
freshclam --quiet || freshclam
systemctl enable --now clamav-freshclam clamav-daemon
for _ in $(seq 1 60); do
  [[ -S /var/run/clamav/clamd.ctl ]] && break
  sleep 5
done
[[ -S /var/run/clamav/clamd.ctl ]] || { echo "ClamAV did not start; check: journalctl -u clamav-daemon" >&2; exit 1; }

echo "==> Scanning service"
id recalltrace-scanner >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin recalltrace-scanner
usermod -aG clamav recalltrace-scanner
mkdir -p "$APP_DIR"
curl -fsSL "$SOURCE/scanner_service.py" -o "$APP_DIR/scanner_service.py"
chmod 0644 "$APP_DIR/scanner_service.py"
NEW_TOKEN=""
if [[ ! -s "$ENV_FILE" ]]; then
  NEW_TOKEN="$(openssl rand -hex 32)"
  umask 077
  printf 'SCANNER_TOKEN=%s\nCLAMD_SOCKET=/var/run/clamav/clamd.ctl\n' "$NEW_TOKEN" > "$ENV_FILE"
fi
chown root:recalltrace-scanner "$ENV_FILE"
chmod 0640 "$ENV_FILE"
cat > /etc/systemd/system/recalltrace-scanner.service <<UNIT
[Unit]
Description=RecallTrace malware scanning service
After=network.target clamav-daemon.service
Requires=clamav-daemon.service

[Service]
User=recalltrace-scanner
Group=recalltrace-scanner
EnvironmentFile=$ENV_FILE
ExecStart=/usr/bin/python3 $APP_DIR/scanner_service.py
Restart=always
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now recalltrace-scanner
systemctl restart recalltrace-scanner

echo "==> HTTPS with Caddy"
cat > /etc/caddy/Caddyfile <<CADDY
$DOMAIN {
	request_body {
		max_size 12MB
	}
	header {
		Strict-Transport-Security "max-age=31536000"
		-Server
	}
	reverse_proxy 127.0.0.1:8088
}
CADDY
systemctl enable caddy
systemctl reload caddy || systemctl restart caddy

echo "==> Checking"
for _ in $(seq 1 30); do
  if curl -fsS "https://$DOMAIN/health" >/dev/null 2>&1; then break; fi
  sleep 5
done
curl -sS "https://$DOMAIN/health" || true
echo
echo
echo "Done. Add these GitHub repository secrets, then redeploy RecallTrace:"
echo "  SCANNER_ENDPOINT = https://$DOMAIN/scan"
if [[ -n "$NEW_TOKEN" ]]; then
  echo "  SCANNER_TOKEN    = $NEW_TOKEN"
  echo "The token is shown only now. It is also stored in $ENV_FILE (root only)."
else
  echo "  SCANNER_TOKEN    = (unchanged; read it with: sudo cat $ENV_FILE)"
fi
