#!/usr/bin/env bash
# Cópia de segurança diária da base de dados (corre pelo temporizador systemd).
# Restaurar: sudo systemctl stop biblioteca-analytics
#            gunzip -c /var/backups/biblioteca-analytics/bd-AAAA-MM-DD.db.gz > /var/lib/biblioteca-analytics/biblioteca_analytics.db
#            chown biblioteca: /var/lib/biblioteca-analytics/biblioteca_analytics.db && sudo systemctl start biblioteca-analytics
set -euo pipefail
BD=/var/lib/biblioteca-analytics/biblioteca_analytics.db
DESTINO=/var/backups/biblioteca-analytics
DIAS=30
[[ -f $BD ]] || { echo "ainda não há base de dados em $BD"; exit 0; }
install -d -m 700 "$DESTINO"
FICHEIRO="$DESTINO/bd-$(date +%Y-%m-%d).db"
sqlite3 "$BD" ".backup '$FICHEIRO'"   # cópia consistente mesmo com o servidor a escrever
gzip -f "$FICHEIRO"
find "$DESTINO" -name 'bd-*.db.gz' -mtime +"$DIAS" -delete
echo "Cópia criada: $FICHEIRO.gz"
