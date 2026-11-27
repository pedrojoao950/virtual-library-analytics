"""Relatório mensal em PDF, enviado por e-mail.

    python relatorio_mensal.py                       # mês anterior: gera o PDF e envia
    python relatorio_mensal.py --mes 2026-10         # um mês concreto
    python relatorio_mensal.py --mes atual           # do dia 1 até hoje (útil para testar)
    python relatorio_mensal.py --so-pdf rel.pdf      # só gera o PDF, não envia

Precisa de: reportlab (Ubuntu/Debian: apt install python3-reportlab).

Configuração do e-mail (variáveis de ambiente, em /etc/biblioteca-analytics/env no servidor):
    BIBLIO_EMAIL_PARA        destinatários, separados por vírgula
    BIBLIO_EMAIL_DE          remetente (no Brevo: um remetente verificado)
    BIBLIO_EMAIL_NOME        nome do remetente (opcional)
    BIBLIO_INSTITUICAO       nome da instituição no cabeçalho do PDF (opcional)
    BIBLIO_EMAIL_LINK_PAINEL=1  inclui no e-mail o link do painel (leva o token: só para destinatários de confiança)
  Envio pelo Brevo (HTTPS; funciona na DigitalOcean, que bloqueia SMTP):
    BIBLIO_BREVO_CHAVE       chave de API do Brevo
  ou por SMTP:
    BIBLIO_SMTP_HOST, BIBLIO_SMTP_PORTA (587), BIBLIO_SMTP_UTILIZADOR, BIBLIO_SMTP_SENHA
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import smtplib
import ssl
import sys
import urllib.error
import urllib.request
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from io import BytesIO
from pathlib import Path

import analytics

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]

# cores (paleta validada para gráficos: azul, laranja, verde-água; tinta e grelha neutras)
AZUL, LARANJA, AGUA = "#257de0", "#f47230", "#00b894"
TINTA, TINTA2, GRELHA, FUNDO = "#191919", "#666666", "#e7e7e7", "#f4f6f9"
BREVO_URL = "https://api.brevo.com/v3/smtp/email"


# ----------------------------------------------------------------------- dados

def intervalo_mes(mes: str, fuso: float) -> tuple[date, date, str]:
    hoje = datetime.now(timezone(timedelta(hours=fuso))).date()
    if mes == "anterior":
        ultimo = hoje.replace(day=1) - timedelta(days=1)
        ini = ultimo.replace(day=1)
        return ini, ultimo, f"{MESES[ini.month - 1]} de {ini.year}"
    if mes == "atual":
        ini = hoje.replace(day=1)
        return ini, hoje, f"{MESES[ini.month - 1]} de {ini.year} (até dia {hoje.day})"
    ano, m = (int(x) for x in mes.split("-"))
    ini = date(ano, m, 1)
    fim = date(ano, m, monthrange(ano, m)[1])
    return ini, min(fim, hoje), f"{MESES[m - 1]} de {ano}"


def recolher(conn, ini: date, fim: date, fuso: float) -> tuple[dict, dict]:
    atual = analytics.metricas(conn, inicio=ini.isoformat(), fim=fim.isoformat(),
                               agrupar="dia", fuso_horas=fuso, limite=10)
    # mês anterior, com o mesmo número de dias, para comparar
    ant_fim = ini - timedelta(days=1)
    ant_ini = ant_fim.replace(day=1)
    ant_fim = min(ant_fim, ant_ini + timedelta(days=(fim - ini).days))
    anterior = analytics.metricas(conn, inicio=ant_ini.isoformat(), fim=ant_fim.isoformat(),
                                  agrupar="dia", fuso_horas=fuso, limite=10)
    return atual, anterior


def num(v, casas=0, sufixo=""):
    if v is None:
        return "—"
    txt = f"{v:,.{casas}f}".replace(",", " ").replace(".", ",")
    return txt + sufixo


def variacao(a, b, pontos=False, melhor_se_menor=False):
    """Texto da comparação com o mês anterior ('+12%', '−3,1 p.p.')."""
    if a is None or b is None:
        return ""
    if pontos:
        d = a - b
        txt = f"{'+' if d >= 0 else '−'}{num(abs(d), 1)} p.p."
    else:
        if not b:
            return "novo" if a else ""
        d = (a - b) / b * 100
        txt = f"{'+' if d >= 0 else '−'}{num(abs(d), 0)}%"
    return txt


def observacoes(r: dict, ra: dict, dados: dict) -> list[str]:
    """Frases curtas com o que mais mudou, para quem não quer ler as tabelas."""
    obs = []
    if not r["pesquisas"] and not r["tempo_leitura_total_min"]:
        return ["Não houve atividade registada neste mês. Confirme que a extensão está instalada "
                "e configurada nos computadores (Opções da extensão → ✓ servidor contactável)."]
    if ra["tempo_leitura_total_min"]:
        d = (r["tempo_leitura_total_min"] - ra["tempo_leitura_total_min"]) / ra["tempo_leitura_total_min"] * 100
        if abs(d) >= 10:
            obs.append(f"O tempo de leitura {'subiu' if d > 0 else 'desceu'} {num(abs(d))}% face ao mês anterior.")
    if r["taxa_sucesso_pesquisa"] is not None:
        if r["taxa_sucesso_pesquisa"] < 50:
            obs.append(f"Só {num(r['taxa_sucesso_pesquisa'], 1)}% das pesquisas levaram a abrir um livro: "
                       "os utilizadores têm dificuldade em encontrar o que procuram.")
        if ra["taxa_sucesso_pesquisa"] is not None and abs(r["taxa_sucesso_pesquisa"] - ra["taxa_sucesso_pesquisa"]) >= 5:
            d = r["taxa_sucesso_pesquisa"] - ra["taxa_sucesso_pesquisa"]
            obs.append(f"A taxa de sucesso da pesquisa {'melhorou' if d > 0 else 'piorou'} {num(abs(d), 1)} pontos.")
    if (r["taxa_sem_resultados"] or 0) >= 15 and dados["nao_encontrados"]:
        top = ", ".join(f"“{x['termo']}”" for x in dados["nao_encontrados"][:3])
        obs.append(f"{num(r['taxa_sem_resultados'], 1)}% das pesquisas não tiveram resultados. "
                   f"Mais procurados sem resultado: {top} — candidatos a aquisição.")
    if dados["mais_lidos"]:
        obs.append(f"O livro mais lido foi “{dados['mais_lidos'][0]['titulo']}” "
                   f"({num(dados['mais_lidos'][0]['minutos'])} min, {dados['mais_lidos'][0]['leitores']} leitores).")
    pcs = [c for c in dados["computadores"] if c["posto"]]
    if pcs:
        parados = [c["posto"] for c in pcs if not c["sessoes"]]
        if parados:
            obs.append(f"Computadores sem uso no mês: {', '.join(parados)}.")
    por_hora = sorted(dados["por_hora"], key=lambda h: h["pesquisas"], reverse=True)
    if por_hora and por_hora[0]["pesquisas"]:
        obs.append(f"Hora de maior procura: {por_hora[0]['hora']}h–{por_hora[0]['hora'] + 1}h.")
    return obs


# ------------------------------------------------------------------------- PDF

def gerar_pdf(dados: dict, anterior: dict, titulo_mes: str, instituicao: str = "") -> bytes:
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle)

    # DejaVu cobre acentos e quase todos os alfabetos dos títulos; senão Helvetica
    fonte, negrito = "Helvetica", "Helvetica-Bold"
    for pasta in ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu"):
        if Path(pasta, "DejaVuSans.ttf").exists():
            pdfmetrics.registerFont(TTFont("DejaVu", str(Path(pasta, "DejaVuSans.ttf"))))
            pdfmetrics.registerFont(TTFont("DejaVu-B", str(Path(pasta, "DejaVuSans-Bold.ttf"))))
            fonte, negrito = "DejaVu", "DejaVu-B"
            break

    c = colors.HexColor
    est = {
        "t": ParagraphStyle("t", fontName=negrito, fontSize=18, leading=22, textColor=c(TINTA)),
        "st": ParagraphStyle("st", fontName=fonte, fontSize=10, leading=14, textColor=c(TINTA2)),
        "h": ParagraphStyle("h", fontName=negrito, fontSize=12.5, leading=16, textColor=c(TINTA), spaceBefore=10, spaceAfter=2),
        "nota": ParagraphStyle("nota", fontName=fonte, fontSize=8.5, leading=11, textColor=c(TINTA2), spaceAfter=4),
        "p": ParagraphStyle("p", fontName=fonte, fontSize=9.5, leading=13, textColor=c(TINTA)),
        "obs": ParagraphStyle("obs", fontName=fonte, fontSize=9.5, leading=13.5, textColor=c(TINTA), leftIndent=10, bulletIndent=0),
        "cel": ParagraphStyle("cel", fontName=fonte, fontSize=8.5, leading=10.5, textColor=c(TINTA)),
        "kv": ParagraphStyle("kv", fontName=negrito, fontSize=15, leading=18, textColor=c(TINTA)),
        "kr": ParagraphStyle("kr", fontName=fonte, fontSize=7.5, leading=9.5, textColor=c(TINTA2)),
        "rodape": ParagraphStyle("rodape", fontName=fonte, fontSize=7.5, textColor=c(TINTA2), alignment=TA_RIGHT),
    }
    P = lambda t, s="p": Paragraph(html.escape(str(t)), est[s])  # noqa: E731
    antes = lambda txt, var: f"mês anterior: {txt}" + (f" ({var})" if var else "")  # noqa: E731
    largura = A4[0] - 30 * mm

    r, ra = dados["resumo"], anterior["resumo"]
    hist = []
    hist.append(P(f"Relatório mensal — {titulo_mes}", "t"))
    sub = "Biblioteca Virtual (Perlego)" + (f" · {instituicao}" if instituicao else "")
    sub += f" · gerado a {datetime.now().strftime('%d/%m/%Y')}"
    hist += [P(sub, "st"), Spacer(1, 8)]

    # --- indicadores (cartões 4 x 2)
    def cartao(rotulo, valor, comp):
        return [Paragraph(html.escape(valor), est["kv"]), Paragraph(html.escape(rotulo), est["kr"]),
                Paragraph(html.escape(comp or " "), est["kr"])]
    kpis = [
        cartao("Sessões", num(r["sessoes"]), antes(num(ra['sessoes']), variacao(r['sessoes'], ra['sessoes']))),
        cartao("Pesquisas", num(r["pesquisas"]), antes(num(ra['pesquisas']), variacao(r['pesquisas'], ra['pesquisas']))),
        cartao("Taxa de sucesso da pesquisa", num(r["taxa_sucesso_pesquisa"], 1, "%"),
               f"mês anterior: {num(ra['taxa_sucesso_pesquisa'], 1, '%')}"),
        cartao("Pesquisas sem resultados", num(r["taxa_sem_resultados"], 1, "%"),
               f"mês anterior: {num(ra['taxa_sem_resultados'], 1, '%')}"),
        cartao("Horas de leitura", num((r["tempo_leitura_total_min"] or 0) / 60, 1),
               antes(num((ra['tempo_leitura_total_min'] or 0) / 60, 1), variacao(r['tempo_leitura_total_min'], ra['tempo_leitura_total_min']))),
        cartao("Leitores (sessões com leitura)", num(r["leitores"]), f"{num(r['livros_lidos'])} livros diferentes"),
        cartao("Tempo médio de pesquisa", num(r["tempo_medio_pesquisa_total_s"], 1, " s"),
               f"mês anterior: {num(ra['tempo_medio_pesquisa_total_s'], 1, ' s')}"),
        cartao("Posição média do clique", num(r["posicao_media_clique"], 1), "1 = primeiro resultado"),
    ]
    grelha = [[kpis[i] for i in range(j, j + 4)] for j in (0, 4)]
    t = Table(grelha, colWidths=[largura / 4] * 4)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), c(FUNDO)),
        ("LINEAFTER", (0, 0), (-2, -1), 3, colors.white), ("LINEBELOW", (0, 0), (-1, 0), 3, colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    hist += [t, Spacer(1, 6)]

    # --- observações
    hist.append(P("Em resumo", "h"))
    for o in observacoes(r, ra, dados):
        hist.append(Paragraph(html.escape(o), est["obs"], bulletText="•"))

    # --- gráficos por dia
    def grafico(titulo, nota, series, cores, nomes=None, altura=120):
        d = Drawing(largura, altura + 20)
        g = VerticalBarChart()
        g.x, g.y, g.width, g.height = 32, 18, largura - 40, altura - 10
        g.data = series
        g.categoryAxis.categoryNames = [p["periodo"][8:].lstrip("0") for p in dados["serie"]]
        g.categoryAxis.labels.fontName = fonte
        g.categoryAxis.labels.fontSize = 6.5
        g.categoryAxis.labels.fillColor = c(TINTA2)
        g.categoryAxis.strokeColor = c("#c2c2c2")
        g.valueAxis.labels.fontName = fonte
        g.valueAxis.labels.fontSize = 7
        g.valueAxis.labels.fillColor = c(TINTA2)
        g.valueAxis.strokeColor = None
        g.valueAxis.gridStrokeColor = c(GRELHA)
        g.valueAxis.visibleGrid = True
        g.valueAxis.valueMin = 0
        maximo = max([max(s) for s in series] + [0]) if len(series) == 1 else max(
            [sum(v) for v in zip(*series)] + [0])
        if not maximo:
            g.valueAxis.valueMax = 1
        g.barSpacing = 0
        g.groupSpacing = 1.5
        if len(series) > 1:
            g.categoryAxis.style = "stacked"
        for i, cor in enumerate(cores):
            g.bars[i].fillColor = c(cor)
            g.bars[i].strokeColor = None
        d.add(g)
        if nomes:  # legenda simples
            x = 32
            for nome, cor in zip(nomes, cores):
                from reportlab.graphics.shapes import Rect
                d.add(Rect(x, altura + 10, 7, 7, fillColor=c(cor), strokeColor=None))
                d.add(String(x + 10, altura + 10.5, nome, fontName=fonte, fontSize=7.5, fillColor=c(TINTA2)))
                x += 12 + pdfmetrics.stringWidth(nome, fonte, 7.5) + 14
        return KeepTogether([P(titulo, "h"), P(nota, "nota"), d])

    s = dados["serie"]
    hist.append(grafico("Minutos de leitura por dia", "Leitura ativa nos computadores da biblioteca (dia do mês no eixo).",
                        [[x["minutos_leitura"] or 0 for x in s]], [AZUL]))
    hist.append(grafico("Pesquisas por dia", "Segundo o que aconteceu depois de cada pesquisa.",
                        [[x["com_sucesso"] for x in s], [x["sem_clique"] for x in s], [x["sem_resultados"] for x in s]],
                        [AZUL, LARANJA, AGUA], ["Abriu um resultado", "Não abriu nenhum", "Sem resultados"]))

    # --- tabelas
    def tabela(titulo, nota, cab, linhas, larg, vazio="Sem dados neste mês."):
        bloco = [P(titulo, "h")]
        if nota:
            bloco.append(P(nota, "nota"))
        if not linhas:
            bloco.append(P(vazio, "nota"))
            return KeepTogether(bloco)
        dadost = [[Paragraph(html.escape(h), est["kr"]) for h in cab]]
        for ln in linhas:
            dadost.append([Paragraph(html.escape(str(v)), est["cel"]) for v in ln])
        tt = Table(dadost, colWidths=[largura * f for f in larg], repeatRows=1)
        tt.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, c(GRELHA)),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        for i in range(1, len(cab)):  # números alinhados à direita
            for j in range(len(dadost)):
                dadost[j][i].style = ParagraphStyle("d", parent=est["cel" if j else "kr"], alignment=TA_RIGHT)
        bloco.append(tt)
        return KeepTogether(bloco)

    hist.append(tabela("Livros mais lidos", "Por tempo total de leitura ativa.",
                       ["Livro", "Minutos", "Leitores"],
                       [[x["titulo"] or x["livro_id"], num(x["minutos"], 1), x["leitores"]] for x in dados["mais_lidos"]],
                       [0.7, 0.15, 0.15]))
    hist.append(tabela("Termos mais pesquisados", "Sucesso = a pesquisa levou a abrir um livro.",
                       ["Termo", "Pesquisas", "Sucesso"],
                       [[x["termo"], x["pesquisas"], num(x["taxa_sucesso"], 1, "%")] for x in dados["mais_procurados_termos"]],
                       [0.7, 0.15, 0.15]))
    hist.append(tabela("Não encontrados", "Pesquisas sem resultados e pedidos de livros — candidatos a aquisição.",
                       ["Termo / título", "Vezes", "Utilizadores"],
                       [[x["termo"], x["vezes"], x["utilizadores"]] for x in dados["nao_encontrados"]],
                       [0.7, 0.15, 0.15]))
    pcs = dados["computadores"]
    hist.append(tabela("Computadores", "Horas com a Perlego aberta e em uso. “Não identificado” = acessos sem nome de computador.",
                       ["Computador", "Horas de uso", "Sessões", "Pesquisas", "Min. leitura"],
                       [[x["posto"] or "Não identificado", num(x["horas_uso"], 1), x["sessoes"], x["pesquisas"],
                         num(x["minutos_leitura"], 0)] for x in pcs],
                       [0.4, 0.15, 0.15, 0.15, 0.15]))

    cnt = dados.get("perlego_counter") or {}
    if cnt.get("disponivel") and cnt.get("mais_lidos"):
        hist.append(tabela("Perlego — relatório oficial (COUNTER)",
                           "Todos os acessos da instituição, incluindo de casa. Aberturas = Unique_Title_Requests.",
                           ["Título", "Aberturas", "Pedidos totais"],
                           [[x["titulo"], x["unicos"], x["total"]] for x in cnt["mais_lidos"]],
                           [0.7, 0.15, 0.15]))

    def rodape(canvas, doc):
        canvas.saveState()
        canvas.setFont(fonte, 7.5)
        canvas.setFillColor(c(TINTA2))
        canvas.drawRightString(A4[0] - 15 * mm, 10 * mm, f"Relatório mensal — {titulo_mes} · página {doc.page}")
        canvas.restoreState()

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm,
                            bottomMargin=17 * mm, title=f"Relatório mensal — {titulo_mes}",
                            author="Biblioteca Analytics")
    doc.build(hist, onFirstPage=rodape, onLaterPages=rodape)
    return buf.getvalue()


# ---------------------------------------------------------------------- e-mail

def corpo_html(dados: dict, anterior: dict, titulo_mes: str, url_painel: str | None) -> str:
    r, ra = dados["resumo"], anterior["resumo"]
    linhas = [
        ("Sessões", num(r["sessoes"]), variacao(r["sessoes"], ra["sessoes"])),
        ("Pesquisas", num(r["pesquisas"]), variacao(r["pesquisas"], ra["pesquisas"])),
        ("Taxa de sucesso da pesquisa", num(r["taxa_sucesso_pesquisa"], 1, "%"),
         variacao(r["taxa_sucesso_pesquisa"], ra["taxa_sucesso_pesquisa"], pontos=True)),
        ("Pesquisas sem resultados", num(r["taxa_sem_resultados"], 1, "%"),
         variacao(r["taxa_sem_resultados"], ra["taxa_sem_resultados"], pontos=True)),
        ("Horas de leitura", num((r["tempo_leitura_total_min"] or 0) / 60, 1),
         variacao(r["tempo_leitura_total_min"], ra["tempo_leitura_total_min"])),
    ]
    tr = "".join(f"<tr><td style='padding:4px 12px 4px 0'>{html.escape(a)}</td>"
                 f"<td style='padding:4px 12px;text-align:right'><b>{html.escape(b)}</b></td>"
                 f"<td style='padding:4px 0;color:#666;text-align:right'>{html.escape(c)}</td></tr>" for a, b, c in linhas)
    obs = "".join(f"<li>{html.escape(o)}</li>" for o in observacoes(r, ra, dados))
    painel = f"<p>Painel com todos os detalhes: <a href='{html.escape(url_painel)}'>abrir painel</a></p>" if url_painel else ""
    return (f"<div style='font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#191919'>"
            f"<h2 style='margin:0 0 8px'>Relatório mensal — {html.escape(titulo_mes)}</h2>"
            f"<p>Segue em anexo o relatório em PDF. Resumo (variação face ao mês anterior):</p>"
            f"<table style='border-collapse:collapse'>{tr}</table>"
            f"<ul>{obs}</ul>{painel}"
            f"<p style='color:#666;font-size:12px'>Enviado automaticamente pelo servidor de métricas da biblioteca.</p></div>")


def enviar(assunto: str, html_corpo: str, pdf: bytes, nome_pdf: str) -> str:
    para = [e.strip() for e in os.environ.get("BIBLIO_EMAIL_PARA", "").split(",") if e.strip()]
    de = os.environ.get("BIBLIO_EMAIL_DE", "").strip()
    nome = os.environ.get("BIBLIO_EMAIL_NOME", "Métricas da Biblioteca").strip()
    if not para or not de:
        raise RuntimeError("falta configurar BIBLIO_EMAIL_PARA e BIBLIO_EMAIL_DE")

    if os.environ.get("BIBLIO_BREVO_CHAVE"):
        corpo = json.dumps({
            "sender": {"name": nome, "email": de},
            "to": [{"email": e} for e in para],
            "subject": assunto,
            "htmlContent": html_corpo,
            "attachment": [{"name": nome_pdf, "content": base64.b64encode(pdf).decode()}],
        }).encode()
        req = urllib.request.Request(BREVO_URL, data=corpo, method="POST", headers={
            "api-key": os.environ["BIBLIO_BREVO_CHAVE"], "content-type": "application/json", "accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return f"enviado pelo Brevo para {', '.join(para)} (HTTP {resp.status})"
        except urllib.error.HTTPError as erro:
            raise RuntimeError(f"o Brevo recusou o envio (HTTP {erro.code}): {erro.read().decode(errors='replace')[:300]}")

    if os.environ.get("BIBLIO_SMTP_HOST"):
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = assunto, f"{nome} <{de}>", ", ".join(para)
        msg.set_content("Relatório mensal em anexo (PDF).")
        msg.add_alternative(html_corpo, subtype="html")
        msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=nome_pdf)
        porta = int(os.environ.get("BIBLIO_SMTP_PORTA", "587"))
        host = os.environ["BIBLIO_SMTP_HOST"]
        ctx = ssl.create_default_context()
        cls = smtplib.SMTP_SSL if porta == 465 else smtplib.SMTP
        kw = {"context": ctx} if porta == 465 else {}
        with cls(host, porta, timeout=60, **kw) as s:
            if porta != 465:
                s.starttls(context=ctx)
            if os.environ.get("BIBLIO_SMTP_UTILIZADOR"):
                s.login(os.environ["BIBLIO_SMTP_UTILIZADOR"], os.environ.get("BIBLIO_SMTP_SENHA", ""))
            s.send_message(msg)
        return f"enviado por SMTP ({host}) para {', '.join(para)}"

    raise RuntimeError("falta configurar o envio: BIBLIO_BREVO_CHAVE ou BIBLIO_SMTP_HOST")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mes", default="anterior", help="'anterior' (por omissão), 'atual' ou AAAA-MM")
    ap.add_argument("--so-pdf", metavar="FICHEIRO", help="só gera o PDF neste ficheiro, sem enviar")
    ap.add_argument("--bd", default=None)
    a = ap.parse_args()

    fuso = float(os.environ.get("BIBLIO_FUSO", "1"))
    ini, fim, titulo_mes = intervalo_mes(a.mes, fuso)
    conn = analytics.ligar(a.bd)
    try:
        dados, anterior = recolher(conn, ini, fim, fuso)
    finally:
        conn.close()
    pdf = gerar_pdf(dados, anterior, titulo_mes, os.environ.get("BIBLIO_INSTITUICAO", ""))
    nome_pdf = f"relatorio-biblioteca-{ini.strftime('%Y-%m')}.pdf"

    if a.so_pdf:
        Path(a.so_pdf).write_bytes(pdf)
        print(f"PDF criado: {a.so_pdf} ({len(pdf) // 1024} KB)")
        return
    # O link do painel leva o token de acesso: só é incluído se for pedido explicitamente.
    url = None
    if os.environ.get("BIBLIO_EMAIL_LINK_PAINEL") == "1" and os.environ.get("BIBLIO_URL_PUBLICO") and os.environ.get("BIBLIO_TOKEN"):
        url = f"{os.environ['BIBLIO_URL_PUBLICO'].rstrip('/')}/?periodo=30d&token={os.environ['BIBLIO_TOKEN']}"
    try:
        print(enviar(f"Relatório mensal da biblioteca — {titulo_mes}",
                     corpo_html(dados, anterior, titulo_mes, url), pdf, nome_pdf))
    except Exception as erro:  # noqa: BLE001
        print(f"ERRO ao enviar o e-mail: {erro}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
