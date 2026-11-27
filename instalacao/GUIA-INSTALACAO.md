# Guia de instalação — servidor na internet

Este guia põe o servidor de métricas num servidor alugado na internet (VPS), com HTTPS.
Assim os computadores da biblioteca enviam os dados para lá, e o painel abre-se em qualquer
lugar (no seu PC, em casa, no telemóvel), mesmo que as redes sejam diferentes.

```
 Computadores da biblioteca            Servidor na internet               O seu PC
 (Chrome/Edge + extensão)  ──HTTPS──►  https://metricas.…  ◄──HTTPS──  painel no navegador
```

Tempo: cerca de 30 minutos. Custo: o aluguer do servidor (≈ 4–6 USD/mês).

---

## 1. Alugar o servidor

Qualquer fornecedor serve (Hetzner, DigitalOcean, Contabo, OVH, Vultr…). Escolha:

- **Sistema:** Ubuntu 24.04 LTS (ou 22.04, ou Debian 12)
- **Tamanho:** o mais pequeno chega (1 CPU, 1–2 GB RAM, 20 GB disco)
- **Região:** a mais próxima (ex.: Europa)
- **Firewall do fornecedor**, se existir: permitir as portas **22** (SSH), **80** e **443**

Anote o **endereço IP** do servidor e a palavra-passe ou chave SSH de `root`.

## 2. Endereço (domínio)

Tem duas opções:

- **Com domínio próprio** (recomendado se a instituição tiver, ex.: `metricas.universidade.ao`):
  peça à informática para criar um registo DNS do tipo **A** que aponte `metricas.universidade.ao`
  para o IP do servidor.
- **Sem domínio:** não faça nada. O instalador usa um endereço gratuito do tipo
  `metricas.203-0-113-5.sslip.io` (o IP com hífenes), que já aponta para o servidor e tem HTTPS.

## 3. Instalar

No seu PC, abra um terminal (Windows: *PowerShell*; Mac/Linux: *Terminal*) e entre no servidor:

```bash
ssh root@IP_DO_SERVIDOR
```

Depois, já dentro do servidor:

```bash
apt-get update && apt-get install -y git
git clone https://github.com/pedrojoao950/virtual-library-analytics
sudo bash virtual-library-analytics/instalacao/instalar.sh metricas.universidade.ao
```

(Sem domínio próprio, a última linha fica só `sudo bash virtual-library-analytics/instalacao/instalar.sh`.)

Se o repositório for privado, o `git clone` pede utilizador e um *token* do GitHub; em alternativa
descarregue o ZIP no GitHub e envie-o para o servidor.

No fim, o instalador mostra algo como:

```
Painel (marque nos favoritos; não partilhe este endereço):
  https://metricas.universidade.ao/?token=Xk3…

Opções da extensão em cada computador da biblioteca:
  Endereço do servidor de métricas:  https://metricas.universidade.ao
  Chave de recolha:                  q9T…
```

**Guarde estes dados.** Ficam também no servidor, em `/etc/biblioteca-analytics/LEIA-ME-credenciais.txt`
(para os ver outra vez: `sudo cat /etc/biblioteca-analytics/LEIA-ME-credenciais.txt`).

O que o instalador faz: instala Python, SQLite e Caddy; cria um utilizador de sistema próprio;
copia o programa para `/opt/biblioteca-analytics`; gera as chaves; põe o servidor a arrancar
sozinho (também depois de reiniciar); configura HTTPS com certificado gratuito renovado
automaticamente; e cria cópias de segurança diárias da base de dados (guardadas 30 dias).

## 4. Abrir o painel

Abra no seu PC o endereço do painel (com `?token=…`) e guarde-o nos favoritos.
Ainda não há dados — aparecem quando os computadores da biblioteca começarem a usar a Perlego.

## 5. Instalar a extensão nos computadores da biblioteca

Em **cada** computador da biblioteca:

1. Copie a pasta `extensao-perlego` (está no ZIP do GitHub) para um sítio fixo, ex.: `C:\BibliotecaAnalytics\extensao-perlego`.
   Não a apague depois — o navegador usa-a a partir daí.
2. No Chrome abra `chrome://extensions` (no Edge, `edge://extensions`).
3. Ative **Modo de programador** e clique **Carregar sem compactação** → escolha a pasta.
4. Em *Biblioteca Analytics — Perlego* clique **Detalhes → Opções da extensão** e preencha:
   - **Endereço do servidor de métricas:** `https://metricas.universidade.ao`
   - **Nome deste computador:** `PC-01` (um nome diferente em cada computador)
   - **Chave de recolha:** a que o instalador mostrou
5. Clique **Guardar**. Deve aparecer **✓ servidor contactável** e **✓ chave de recolha aceite**.

No **primeiro** computador, ligue também o **Modo diagnóstico**, faça uma pesquisa na Perlego,
abra e leia um livro durante um minuto, e confirme no canto da página o que é detetado
(e depois no painel). Se algo não for detetado, ajuste *Endereços da Perlego (avançado)*.
Desligue o diagnóstico no fim.

> O Chrome pode mostrar ao arrancar um aviso sobre "extensões em modo de programador";
> basta fechá-lo. Para muitos computadores, a informática pode instalar e configurar a extensão
> por política (ver o `README.md`, secção da extensão).

## 6. Relatórios oficiais da Perlego (opcional)

Quando tiver acesso de administrador à Perlego, descarregue o relatório COUNTER **TR_B1** e
importe-o no painel, no cartão *Perlego — relatórios oficiais*, botão **Importar relatório…**.

## 7. Relatório mensal em PDF por e-mail

No dia 1 de cada mês, o servidor envia por e-mail um PDF com o mês anterior: indicadores
comparados com o mês anterior, um resumo em frases, leitura e pesquisas por dia, livros mais
lidos, termos mais pesquisados, não encontrados, uso por computador e (se importado) o relatório
COUNTER da Perlego.

A DigitalOcean **bloqueia o envio de e-mail por SMTP** em contas novas, por isso use o **Brevo**
(gratuito até 300 e-mails/dia, envia por HTTPS):

1. Crie uma conta em https://www.brevo.com (plano *Free*).
2. **Remetente:** menu **Senders, Domains & Dedicated IPs → Senders → Add a sender**. Use um
   e-mail seu (ex.: o da biblioteca) e confirme-o pelo link que o Brevo envia.
3. **Chave de API:** menu (canto superior direito) **SMTP & API → API Keys → Generate a new API key**.
   Copie a chave (`xkeysib-…`); só é mostrada uma vez.
4. **IPs autorizados:** em **Security → Authorised IPs**, adicione o IP do servidor da DigitalOcean
   (ou desative o bloqueio). Sem isto, o Brevo recusa o envio com "unrecognised IP address".

No servidor:

```bash
cd virtual-library-analytics && git pull
sudo bash instalacao/configurar-email.sh
```

O script pergunta os destinatários, o nome da instituição, o remetente (o mesmo do passo 2) e a
chave do Brevo, agenda o envio mensal e oferece-se para enviar logo um e-mail de teste com o mês
atual. Pode correr outra vez para mudar destinatários ou chaves.

| Tarefa | Comando |
|---|---|
| Enviar o relatório do mês anterior agora | `sudo systemctl start biblioteca-relatorio-mensal` |
| Ver se correu bem | `journalctl -u biblioteca-relatorio-mensal -n 20` |
| Ver a data do próximo envio | `systemctl list-timers biblioteca-relatorio-mensal.timer` |
| Gerar só o PDF de um mês | `cd /opt/biblioteca-analytics/app && sudo -u biblioteca python3 relatorio_mensal.py --bd /var/lib/biblioteca-analytics/biblioteca_analytics.db --mes 2026-10 --so-pdf /tmp/rel.pdf` |

Se preferir outro servidor de e-mail (por exemplo o da instituição, fora da DigitalOcean),
escolha a opção 2 (SMTP) no script. O e-mail **não** leva o link do painel, porque esse link dá
acesso aos dados; para o incluir, acrescente `BIBLIO_EMAIL_LINK_PAINEL=1` e
`BIBLIO_URL_PUBLICO=https://…` a `/etc/biblioteca-analytics/env`.

---

## Manutenção

| Tarefa | Comando (no servidor) |
|---|---|
| Ver se está a funcionar | `systemctl status biblioteca-analytics` |
| Ver registos | `journalctl -u biblioteca-analytics -f` |
| Atualizar o programa | `cd virtual-library-analytics && git pull && sudo bash instalacao/atualizar.sh` |
| Fazer uma cópia agora | `sudo /usr/local/sbin/biblioteca-analytics-backup` |
| Ver as cópias | `ls -lh /var/backups/biblioteca-analytics` |
| Mudar configurações | `sudo nano /etc/biblioteca-analytics/env` e depois `sudo systemctl restart biblioteca-analytics` |
| Ver os dados de acesso | `sudo cat /etc/biblioteca-analytics/LEIA-ME-credenciais.txt` |

A atualização faz uma cópia de segurança antes e, se a nova versão não arrancar, repõe a anterior.

**Restaurar uma cópia de segurança:**

```bash
sudo systemctl stop biblioteca-analytics
gunzip -c /var/backups/biblioteca-analytics/bd-AAAA-MM-DD.db.gz | sudo tee /var/lib/biblioteca-analytics/biblioteca_analytics.db >/dev/null
sudo rm -f /var/lib/biblioteca-analytics/biblioteca_analytics.db-wal /var/lib/biblioteca-analytics/biblioteca_analytics.db-shm
sudo chown biblioteca: /var/lib/biblioteca-analytics/biblioteca_analytics.db
sudo systemctl start biblioteca-analytics
```

As cópias ficam no mesmo servidor. Para se proteger de perder o servidor inteiro, ative também
as *snapshots/backups* do fornecedor, ou copie a pasta `/var/backups/biblioteca-analytics` para outro lado de vez em quando.

**Trocar as chaves** (se o endereço do painel ou a chave de recolha forem partilhados por engano):
edite `BIBLIO_TOKEN` e/ou `BIBLIO_CHAVE_RECOLHA` em `/etc/biblioteca-analytics/env`, reinicie
o serviço, e atualize a chave nas opções da extensão de cada computador. Enquanto a chave
estiver errada, a extensão guarda os dados e envia-os quando for corrigida.

## Problemas comuns

| Sintoma | O que verificar |
|---|---|
| O instalador diz que o HTTPS ainda não respondeu | O DNS do domínio aponta para o IP do servidor? As portas 80 e 443 estão abertas na firewall do fornecedor? `journalctl -u caddy -n 50` |
| Opções da extensão: "não foi possível contactar o servidor" | O endereço começa por `https://` e não tem `/` no fim? A rede da biblioteca bloqueia o site? (teste abrir `https://…/api/saude` no navegador desse computador) |
| "chave de recolha errada" | Copie outra vez a chave, sem espaços |
| O painel diz "Token em falta ou inválido" | Use o endereço completo com `?token=…` |
| E-mail mensal não chega | `journalctl -u biblioteca-relatorio-mensal -n 20`; veja a pasta de spam; no Brevo confirme o remetente e os IPs autorizados |
| Painel sem dados de um computador | Opções da extensão desse computador: "Eventos à espera de envio" e "Último erro" |

## Segurança e privacidade

- Tudo passa por HTTPS. O servidor só aceita dados com a **chave de recolha** e o painel só abre com o **token**.
- Não são recolhidos nomes, e-mails, IPs nem dados das contas Perlego. As pesquisas ficam guardadas como texto.
- Informe os utilizadores da biblioteca (por exemplo, com um aviso junto aos computadores) de que
  é recolhida informação anónima de utilização da Perlego para melhorar o serviço.
