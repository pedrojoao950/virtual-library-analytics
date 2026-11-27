#!/usr/bin/env bash
# Confere a configuração do relatório por e-mail (Brevo/SMTP) sem enviar nada.
#   sudo bash instalacao/verificar-email.sh
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "corra com sudo" >&2; exit 1; }
exec systemd-run --quiet --wait --pipe --collect -p User=biblioteca -p EnvironmentFile=/etc/biblioteca-analytics/env \
  -p WorkingDirectory=/opt/biblioteca-analytics/app \
  /usr/bin/python3 /opt/biblioteca-analytics/app/relatorio_mensal.py --verificar-email
