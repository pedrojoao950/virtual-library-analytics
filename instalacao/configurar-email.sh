#!/usr/bin/env bash
# Configura o relatório mensal em PDF enviado por e-mail (dia 1 de cada mês, mês anterior).
#
#   cd virtual-library-analytics && git pull
#   sudo bash instalacao/configurar-email.sh
#
# Pode correr outra vez para mudar destinatários ou chaves.
set -euo pipefail
ENV_FILE=/etc/biblioteca-analytics/env
ORIGEM="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

info()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
erro()  { printf '\033[1;31mERRO: %s\033[0m\n' "$*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || erro "corra com sudo"
[[ -f $ENV_FILE ]] || erro "o servidor ainda não foi instalado (falta $ENV_FILE): corra primeiro instalar.sh"

info "A instalar o gerador de PDF e a atualizar o programa…"
DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3-reportlab fonts-dejavu-core >/dev/null
bash "$ORIGEM/instalacao/atualizar.sh"

# valor atual de uma variável do ficheiro de configuração
atual() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' || true; }
perguntar() {  # perguntar VAR "Pergunta" [secreto]
  local var=$1 texto=$2 secreto=${3:-} antigo valor
  antigo="$(atual "$var")"
  local sugestao=""
  if [[ -n $antigo ]]; then
    if [[ -n $secreto ]]; then sugestao=" [Enter = manter a atual]"; else sugestao=" [$antigo]"; fi
  fi
  if [[ -n $secreto ]]; then read -r -s -p "$texto$sugestao: " valor; echo; else read -r -p "$texto$sugestao: " valor; fi
  valor="${valor:-$antigo}"
  [[ $valor != *[\"\\\$\`]* ]] || erro "o valor não pode ter aspas, \\, \$ nem \`"
  printf -v "$var" '%s' "$valor"
}
definir() {  # escreve VAR="valor" no ficheiro de configuração (substitui se já existir)
  python3 - "$ENV_FILE" "$1" "$2" <<'PY'
import sys
f, k, v = sys.argv[1:]
linhas = [l for l in open(f, encoding="utf-8").read().splitlines() if not l.startswith(k + "=")]
if v:
    linhas.append(f'{k}="{v}"')
open(f, "w", encoding="utf-8").write("\n".join(linhas) + "\n")
PY
}

info "Dados do relatório"
perguntar BIBLIO_EMAIL_PARA "Enviar para (e-mails separados por vírgula)"
[[ $BIBLIO_EMAIL_PARA == *@* ]] || erro "indique pelo menos um e-mail"
perguntar BIBLIO_INSTITUICAO "Nome da instituição (aparece no PDF)"
perguntar BIBLIO_EMAIL_DE "E-mail do remetente (no Brevo: o remetente verificado)"
[[ $BIBLIO_EMAIL_DE == *@* ]] || erro "o remetente tem de ser um e-mail"
perguntar BIBLIO_EMAIL_NOME "Nome do remetente"
BIBLIO_EMAIL_NOME="${BIBLIO_EMAIL_NOME:-Métricas da Biblioteca}"

echo
echo "Como enviar o e-mail?"
echo "  1) Brevo (recomendado na DigitalOcean, que bloqueia o envio por SMTP)"
echo "  2) Servidor SMTP (Gmail, Outlook, servidor da instituição…)"
METODO_ATUAL=1; [[ -n "$(atual BIBLIO_SMTP_HOST)" ]] && METODO_ATUAL=2
read -r -p "Escolha 1 ou 2 [$METODO_ATUAL]: " METODO
METODO="${METODO:-$METODO_ATUAL}"

if [[ $METODO == 1 ]]; then
  perguntar BIBLIO_BREVO_CHAVE "Chave de API do Brevo (xkeysib-…)" secreto
  [[ -n $BIBLIO_BREVO_CHAVE ]] || erro "falta a chave do Brevo"
  for v in BIBLIO_SMTP_HOST BIBLIO_SMTP_PORTA BIBLIO_SMTP_UTILIZADOR BIBLIO_SMTP_SENHA; do definir "$v" ""; done
  definir BIBLIO_BREVO_CHAVE "$BIBLIO_BREVO_CHAVE"
else
  perguntar BIBLIO_SMTP_HOST "Servidor SMTP (ex.: smtp.gmail.com)"
  perguntar BIBLIO_SMTP_PORTA "Porta (587 ou 465)"
  BIBLIO_SMTP_PORTA="${BIBLIO_SMTP_PORTA:-587}"
  perguntar BIBLIO_SMTP_UTILIZADOR "Utilizador SMTP"
  perguntar BIBLIO_SMTP_SENHA "Senha SMTP (no Gmail: palavra-passe de aplicação)" secreto
  definir BIBLIO_BREVO_CHAVE ""
  for v in BIBLIO_SMTP_HOST BIBLIO_SMTP_PORTA BIBLIO_SMTP_UTILIZADOR BIBLIO_SMTP_SENHA; do definir "$v" "${!v}"; done
fi
for v in BIBLIO_EMAIL_PARA BIBLIO_INSTITUICAO BIBLIO_EMAIL_DE BIBLIO_EMAIL_NOME; do definir "$v" "${!v}"; done
chmod 600 "$ENV_FILE"

info "A agendar o envio para o dia 1 de cada mês…"
install -m 644 "$ORIGEM/instalacao/biblioteca-relatorio-mensal.service" /etc/systemd/system/
install -m 644 "$ORIGEM/instalacao/biblioteca-relatorio-mensal.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now biblioteca-relatorio-mensal.timer >/dev/null

echo
read -r -p "Enviar agora um e-mail de teste com o relatório do mês atual (até hoje)? [S/n] " TESTE
if [[ ! $TESTE =~ ^[nN] ]]; then
  info "A enviar o e-mail de teste…"
  if systemd-run --quiet --wait --pipe --collect -p User=biblioteca -p EnvironmentFile="$ENV_FILE" \
       -p WorkingDirectory=/opt/biblioteca-analytics/app \
       /usr/bin/python3 /opt/biblioteca-analytics/app/relatorio_mensal.py --mes atual; then
    echo "Verifique a caixa de correio (e a pasta de spam/lixo)."
  else
    echo "O envio falhou. Veja a mensagem acima e o guia (secção Relatório mensal)."
  fi
fi

info "Configurado."
echo "Próximo envio automático: $(systemctl show biblioteca-relatorio-mensal.timer -p NextElapseUSecRealtime --value 2>/dev/null || echo 'dia 1 do próximo mês')"
echo "Enviar manualmente:  sudo systemctl start biblioteca-relatorio-mensal"
echo "Ver o resultado:     journalctl -u biblioteca-relatorio-mensal -n 20"
