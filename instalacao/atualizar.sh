#!/usr/bin/env bash
# Atualiza o programa sem perder dados nem chaves.
#
#   cd virtual-library-analytics && git pull
#   sudo bash instalacao/atualizar.sh
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "corra com sudo" >&2; exit 1; }
ORIGEM="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR=/opt/biblioteca-analytics

/usr/local/sbin/biblioteca-analytics-backup   # cópia de segurança antes de atualizar
rm -rf "$APP_DIR/app.novo"
mkdir -p "$APP_DIR/app.novo"
cp -a "$ORIGEM"/{servidor.py,analytics.py,relatorio.py,importar_counter.py,static} "$APP_DIR/app.novo/"
chown -R root:root "$APP_DIR/app.novo"
rm -rf "$APP_DIR/app.antigo"
mv "$APP_DIR/app" "$APP_DIR/app.antigo"
mv "$APP_DIR/app.novo" "$APP_DIR/app"
install -m 644 "$ORIGEM/instalacao/biblioteca-analytics.service" /etc/systemd/system/biblioteca-analytics.service
install -m 755 "$ORIGEM/instalacao/backup.sh" /usr/local/sbin/biblioteca-analytics-backup
systemctl daemon-reload
systemctl restart biblioteca-analytics

for _ in $(seq 1 20); do
  if curl -fsS http://127.0.0.1:8080/api/saude >/dev/null 2>&1; then echo "Atualizado e a funcionar."; exit 0; fi
  sleep 1
done
echo "O serviço não respondeu; a repor a versão anterior…" >&2
rm -rf "$APP_DIR/app" && mv "$APP_DIR/app.antigo" "$APP_DIR/app"
systemctl restart biblioteca-analytics
echo "Versão anterior reposta. Veja: journalctl -u biblioteca-analytics -n 50" >&2
exit 1
