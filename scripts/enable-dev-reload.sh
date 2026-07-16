#!/bin/bash
set -euo pipefail

mkdir -p /etc/systemd/system/mhserver-web.service.d
cat >/etc/systemd/system/mhserver-web.service.d/override.conf <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/bin/python3 -m gunicorn --reload --workers 1 --bind 127.0.0.1:5000 --timeout 120 --no-control-socket app.app:app
EOF

systemctl daemon-reload
systemctl restart mhserver-web
systemctl status mhserver-web --no-pager -n 20
