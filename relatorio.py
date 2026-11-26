"""Relatório de métricas em linha de comandos (sem precisar do servidor).

    python relatorio.py                         # últimos 30 dias, por dia
    python relatorio.py --periodo 7d --agrupar dia
    python relatorio.py --periodo 12m --agrupar mes --csv relatorios/
    python relatorio.py --inicio 2026-01-01 --fim 2026-03-31 --agrupar semana --json
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import analytics

ROTULOS = {
    "sessoes": "Sessões", "utilizadores": "Utilizadores únicos", "vistas_pagina": "Páginas vistas",
    "vistas_livro": "Fichas de livro abertas", "duracao_media_sessao_min": "Duração média da sessão (min)",
    "pesquisas": "Pesquisas", "pesquisas_por_sessao": "Pesquisas por sessão",
    "taxa_sucesso_pesquisa": "Taxa de sucesso da pesquisa (%)", "taxa_sem_resultados": "Pesquisas sem resultados (%)",
    "taxa_abandono_pesquisa": "Pesquisas com resultados mas sem clique (%)",
    "tempo_medio_escrita_pesquisa_s": "Tempo médio a escrever a pesquisa (s)",
    "tempo_medio_ate_encontrar_s": "Tempo médio a escolher o resultado (s)",
    "tempo_medio_pesquisa_total_s": "Tempo médio total de pesquisa (s)",
    "posicao_media_clique": "Posição média do resultado clicado",
    "pedidos_nao_encontrados": "Pedidos de livros não encontrados",
    "tempo_leitura_total_min": "Tempo total de leitura (min)", "leitores": "Leitores",
    "livros_lidos": "Livros diferentes lidos", "tempo_leitura_medio_por_leitor_min": "Leitura média por leitor (min)",
}


def _tabela(titulo, linhas, colunas):
    print(f"\n{titulo}")
    print("-" * len(titulo))
    if not linhas:
        print("  (sem dados)")
        return
    larg = [max(len(c[1]), *(len(str(r.get(c[0], "") if r.get(c[0]) is not None else "—")) for r in linhas))
            for c in colunas]
    larg[0] = min(larg[0], 45)
    print("  " + "  ".join(c[1].ljust(w) for c, w in zip(colunas, larg)))
    for r in linhas:
        cel = [str(r.get(c[0]) if r.get(c[0]) is not None else "—") for c in colunas]
        cel[0] = cel[0][:45]
        print("  " + "  ".join(v.ljust(w) if i == 0 else v.rjust(w) for i, (v, w) in enumerate(zip(cel, larg))))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--periodo", default="30d", choices=["hoje", "7d", "30d", "90d", "12m"])
    ap.add_argument("--inicio", help="AAAA-MM-DD (substitui --periodo)")
    ap.add_argument("--fim", help="AAAA-MM-DD")
    ap.add_argument("--agrupar", default="dia", choices=analytics.AGRUPAMENTOS)
    ap.add_argument("--limite", type=int, default=10)
    ap.add_argument("--bd", default=None)
    ap.add_argument("--fuso", type=float, default=float(os.environ.get("BIBLIO_FUSO", "1")))
    ap.add_argument("--json", action="store_true", help="imprime tudo em JSON")
    ap.add_argument("--csv", metavar="PASTA", help="exporta cada tabela para CSV nesta pasta")
    a = ap.parse_args()

    conn = analytics.ligar(a.bd)
    d = analytics.metricas(conn, a.periodo, a.inicio, a.fim, a.agrupar, a.fuso, a.limite)

    if a.csv:
        pasta = Path(a.csv)
        pasta.mkdir(parents=True, exist_ok=True)
        for t in analytics.TABELAS_EXPORTAVEIS:
            (pasta / f"{t}.csv").write_text("﻿" + analytics.para_csv(d, t), encoding="utf-8")
        print(f"CSV exportados para {pasta.resolve()}")
    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return
    if a.csv:
        return

    iv = d["intervalo"]
    print(f"Biblioteca Virtual — {iv['inicio']} a {iv['fim']} (agrupado por {iv['agrupar']})")
    print("\nResumo")
    print("------")
    for k, v in d["resumo"].items():
        print(f"  {ROTULOS.get(k, k):<48} {'—' if v is None else v}")
    _tabela("Livros mais lidos", d["mais_lidos"],
            [("titulo", "Livro"), ("minutos", "Minutos"), ("leitores", "Leitores")])
    _tabela("Livros mais procurados", d["mais_procurados_livros"],
            [("titulo", "Livro"), ("vistas", "Fichas"), ("cliques_pesquisa", "Cliques"), ("utilizadores", "Utiliz.")])
    _tabela("Termos mais pesquisados", d["mais_procurados_termos"],
            [("termo", "Termo"), ("pesquisas", "Pesquisas"), ("taxa_sucesso", "Sucesso %")])
    _tabela("Não encontrados", d["nao_encontrados"],
            [("termo", "Termo / título"), ("vezes", "Vezes"), ("pedidos_explicitos", "Pedidos"), ("ultima_vez", "Última vez")])
    _tabela(f"Evolução por {iv['agrupar']}", d["serie"],
            [("periodo", "Período"), ("sessoes", "Sessões"), ("pesquisas", "Pesquisas"), ("sem_resultados", "Sem res."),
             ("tempo_medio_pesquisa_s", "T. pesq. (s)"), ("minutos_leitura", "Min. leitura"), ("leitores", "Leitores")])


if __name__ == "__main__":
    main()
