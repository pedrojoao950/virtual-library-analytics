#!/usr/bin/env bash
# Instala o servidor de métricas da biblioteca num servidor Ubuntu 22.04/24.04 ou Debian 12.
#
#   git clone https://github.com/pedrojoao950/virtual-library-analytics
#   sudo bash virtual-library-analytics/instalacao/instalar.sh metricas.exemplo.ao
#
# Sem domínio próprio, omita o argumento: usa-se um endereço gratuito <ip>.sslip.io.
# Pode correr outra vez sem perder dados nem mudar as chaves (para reparar ou mudar o domínio).
set -euo pipefail

APP_DIR=/opt/biblioteca-analytics
DADOS_DIR=/var/lib/biblioteca-analytics
BACKUP_DIR=/var/backups/biblioteca-analytics
CONF_DIR=/etc/biblioteca-analytics
ENV_FILE=$CONF_DIR/env
UTILIZADOR=biblioteca
PORTA_INTERNA=8080
ORIGEM="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

info()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
aviso() { printf '\033[1;33mAVISO: %s\033[0m\n' "$*"; }
erro()  { printf '\033[1;31mERRO: %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || erro "corra com sudo: sudo bash $0 ${1:-}"
command -v apt-get >/dev/null || erro "este instalador é para Ubuntu ou Debian"
[[ -f "$ORIGEM/servidor.py" ]] || erro "não encontrei servidor.py em $ORIGEM"

# ------------------------------------------------------------------ pacotes
info "A instalar pacotes (python3, sqlite3, caddy)…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q python3 python3-reportlab fonts-dejavu-core sqlite3 curl ca-certificates gnupg debian-keyring debian-archive-keyring apt-transport-https
if ! apt-cache policy caddy 2>/dev/null | grep -q 'Candidate: [0-9]'; then
  # repositório oficial do Caddy (https://caddyserver.com/docs/install)
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q
fi
apt-get install -y -q caddy

python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || erro "é preciso Python 3.10 ou mais recente"

# ------------------------------------------------------------------ domínio
DOMINIO="${1:-}"
IP_PUBLICO="$(curl -4 -fsS --max-time 10 https://api.ipify.org || true)"
if [[ -z "$DOMINIO" ]]; then
  [[ -n "$IP_PUBLICO" ]] || erro "não consegui descobrir o IP público; indique o domínio: sudo bash $0 metricas.exemplo.ao"
  DOMINIO="metricas.${IP_PUBLICO//./-}.sslip.io"
  info "Sem domínio indicado: vou usar $DOMINIO"
else
  IP_DOMINIO="$(getent ahostsv4 "$DOMINIO" | awk 'NR==1{print $1}' || true)"
  if [[ -z "$IP_DOMINIO" ]]; then
    aviso "o domínio $DOMINIO ainda não aponta para nenhum IP. Crie um registo DNS do tipo A para $IP_PUBLICO."
  elif [[ -n "$IP_PUBLICO" && "$IP_DOMINIO" != "$IP_PUBLICO" ]]; then
    aviso "$DOMINIO aponta para $IP_DOMINIO, mas este servidor é $IP_PUBLICO. O certificado HTTPS vai falhar até corrigir o DNS."
  fi
fi

# ------------------------------------------------------------------ utilizador e pastas
info "A preparar utilizador e pastas…"
id "$UTILIZADOR" &>/dev/null || useradd --system --home "$DADOS_DIR" --shell /usr/sbin/nologin "$UTILIZADOR"
install -d -o "$UTILIZADOR" -g "$UTILIZADOR" -m 750 "$DADOS_DIR"
install -d -o root -g root -m 700 "$BACKUP_DIR" "$CONF_DIR"
install -d -o root -g root -m 755 "$APP_DIR"

info "A copiar o programa para $APP_DIR…"
rm -rf "$APP_DIR/app.novo"
mkdir -p "$APP_DIR/app.novo"
cp -a "$ORIGEM"/{servidor.py,analytics.py,relatorio.py,relatorio_mensal.py,importar_counter.py,static} "$APP_DIR/app.novo/"
chown -R root:root "$APP_DIR/app.novo"
rm -rf "$APP_DIR/app.antigo"
[[ -d "$APP_DIR/app" ]] && mv "$APP_DIR/app" "$APP_DIR/app.antigo"
mv "$APP_DIR/app.novo" "$APP_DIR/app"

# ------------------------------------------------------------------ configuração e chaves
gerar() { python3 -c 'import secrets; print(secrets.token_urlsafe(24))'; }
if [[ ! -f "$ENV_FILE" ]]; then
  info "A gerar as chaves de acesso…"
  umask 077
  cat > "$ENV_FILE" <<CONF
# Configuração do servidor de métricas. Depois de mudar: sudo systemctl restart biblioteca-analytics
BIBLIO_BD=$DADOS_DIR/biblioteca_analytics.db
BIBLIO_HOST=127.0.0.1
BIBLIO_PORTA=$PORTA_INTERNA
BIBLIO_TOKEN=$(gerar)
BIBLIO_CHAVE_RECOLHA=$(gerar)
BIBLIO_CONFIAR_PROXY=1
BIBLIO_DEMO=0
BIBLIO_FUSO=1
CONF
  umask 022
fi
chmod 600 "$ENV_FILE"
# shellcheck disable=SC1090
source "$ENV_FILE"

# ------------------------------------------------------------------ serviço
info "A configurar o serviço (systemd)…"
install -m 644 "$ORIGEM/instalacao/biblioteca-analytics.service" /etc/systemd/system/biblioteca-analytics.service
install -m 755 "$ORIGEM/instalacao/backup.sh" /usr/local/sbin/biblioteca-analytics-backup
install -m 644 "$ORIGEM/instalacao/biblioteca-analytics-backup.service" /etc/systemd/system/
install -m 644 "$ORIGEM/instalacao/biblioteca-analytics-backup.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now biblioteca-analytics.service biblioteca-analytics-backup.timer
systemctl restart biblioteca-analytics.service

# ------------------------------------------------------------------ HTTPS (Caddy)
info "A configurar HTTPS para $DOMINIO…"
if [[ -f /etc/caddy/Caddyfile ]] && ! grep -q 'biblioteca-analytics' /etc/caddy/Caddyfile; then
  cp /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.antes-biblioteca-$(date +%Y%m%d%H%M%S)"
fi
sed -e "s/__DOMINIO__/$DOMINIO/g" -e "s/__PORTA__/$PORTA_INTERNA/g" "$ORIGEM/instalacao/Caddyfile" > /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
systemctl enable caddy >/dev/null
systemctl reload caddy 2>/dev/null || systemctl restart caddy

if command -v ufw >/dev/null && ufw status | grep -q 'Status: active'; then
  ufw allow 80/tcp >/dev/null && ufw allow 443/tcp >/dev/null
  info "Firewall (ufw): portas 80 e 443 abertas."
fi

# ------------------------------------------------------------------ verificação
info "A verificar…"
for _ in $(seq 1 20); do
  curl -fsS "http://127.0.0.1:$PORTA_INTERNA/api/saude" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "http://127.0.0.1:$PORTA_INTERNA/api/saude" >/dev/null || erro "o serviço não arrancou: veja 'journalctl -u biblioteca-analytics -n 50'"

HTTPS_OK=nao
for _ in $(seq 1 30); do
  if curl -fsS --max-time 5 "https://$DOMINIO/api/saude" >/dev/null 2>&1; then HTTPS_OK=sim; break; fi
  sleep 2
done

RESUMO="$CONF_DIR/LEIA-ME-credenciais.txt"
umask 077
cat > "$RESUMO" <<FIM
Servidor de métricas da biblioteca — dados de acesso (guarde em lugar seguro)
=============================================================================

Painel (marque nos favoritos; não partilhe este endereço):
  https://$DOMINIO/?token=$BIBLIO_TOKEN

Opções da extensão em cada computador da biblioteca:
  Endereço do servidor de métricas:  https://$DOMINIO
  Chave de recolha:                  $BIBLIO_CHAVE_RECOLHA
  Nome deste computador:             PC-01, PC-02, ...

Cópias de segurança diárias em: $BACKUP_DIR (30 dias)
Configuração:                   $ENV_FILE
Registos:                       journalctl -u biblioteca-analytics -f
FIM
umask 022

echo
cat "$RESUMO"
echo
echo "(Este resumo ficou guardado em $RESUMO)"
if [[ $HTTPS_OK == sim ]]; then
  info "Instalação concluída. HTTPS a funcionar."
else
  aviso "o serviço está a correr, mas o HTTPS em https://$DOMINIO ainda não respondeu."
  echo "  - confirme que o DNS de $DOMINIO aponta para ${IP_PUBLICO:-este servidor};"
  echo "  - confirme que as portas 80 e 443 estão abertas na firewall do fornecedor;"
  echo "  - veja o certificado com: journalctl -u caddy -n 50"
fi
