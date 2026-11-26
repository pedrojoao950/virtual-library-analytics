"""Gera dados fictícios para experimentar o painel sem uma biblioteca real.

    python gerar_dados_demo.py              # 90 dias, ~40 sessões/dia
    python gerar_dados_demo.py --dias 365 --sessoes 60 --bd outro.db
"""

from __future__ import annotations

import argparse
import random
import time
import uuid

import analytics

LIVROS = [
    ("mayombe", "Mayombe", 9), ("geracao-utopia", "A Geração da Utopia", 5),
    ("luuanda", "Luuanda", 6), ("vendedor-passados", "O Vendedor de Passados", 7),
    ("teoria-esquecimento", "Teoria Geral do Esquecimento", 5), ("sagrada-esperanca", "Sagrada Esperança", 4),
    ("bom-dia-camaradas", "Bom Dia Camaradas", 6), ("terra-sonambula", "Terra Sonâmbula", 4),
    ("os-lusiadas", "Os Lusíadas", 3), ("memorial-convento", "Memorial do Convento", 2),
    ("calculo-1", "Cálculo — Volume 1", 8), ("algoritmos", "Introdução aos Algoritmos", 6),
    ("direito-constitucional", "Direito Constitucional Angolano", 7),
]
TERMOS_LIVRO = {
    "mayombe": ["mayombe", "pepetela"], "geracao-utopia": ["geração da utopia", "pepetela"],
    "luuanda": ["luuanda", "luandino"], "vendedor-passados": ["agualusa", "vendedor de passados"],
    "teoria-esquecimento": ["agualusa", "teoria geral do esquecimento"], "sagrada-esperanca": ["agostinho neto", "poesia angolana"],
    "bom-dia-camaradas": ["ondjaki"], "terra-sonambula": ["mia couto"], "os-lusiadas": ["camões", "lusiadas"],
    "memorial-convento": ["saramago"], "calculo-1": ["calculo", "cálculo stewart"], "algoritmos": ["algoritmos", "cormen"],
    "direito-constitucional": ["direito constitucional", "constituição angola"],
}
NAO_EXISTEM = ["harry potter", "contabilidade geral", "anatomia humana netter", "economia angolana",
               "química orgânica", "o alquimista", "programação python", "metodologia científica"]
POSTOS = [f"PC-{i:02d}" for i in range(1, 9)]  # computadores da sala de leitura
PESO_POSTOS = [6, 6, 5, 5, 4, 3, 2, 1]
HORAS = [0, 0, 0, 0, 0, 0, 1, 2, 4, 6, 7, 6, 4, 5, 7, 7, 6, 5, 5, 6, 6, 4, 2, 1]


def gerar(conn, dias: int, sessoes_dia: int, semente: int = 7) -> int:
    rnd = random.Random(semente)
    agora = int(time.time() * 1000)
    utilizadores = [uuid.uuid4().hex for _ in range(max(20, sessoes_dia * 4))]
    pesos = [p for _, _, p in LIVROS]
    eventos = []
    for dia in range(dias, -1, -1):
        fds = time.gmtime((agora - dia * 86400000) / 1000).tm_wday >= 5
        n = int(sessoes_dia * (0.55 if fds else 1.0) * rnd.uniform(0.75, 1.25) * (1 + 0.003 * (dias - dia)))
        for _ in range(n):
            hora = rnd.choices(range(24), HORAS)[0]
            t = agora - dia * 86400000 - (agora % 86400000) + hora * 3600000 + rnd.randint(0, 3599999) - 3600000
            if t > agora:
                continue
            s, u = uuid.uuid4().hex, rnd.choice(utilizadores)
            # ~70 % dos acessos vêm dos computadores da biblioteca; o resto de casa (sem posto)
            posto = rnd.choices(POSTOS, PESO_POSTOS)[0] if rnd.random() < 0.7 else None
            t0 = t
            ev = lambda tipo, **k: eventos.append({"tipo": tipo, "ts": t, "sessao": s, "utilizador": u,  # noqa: E731
                                                   "posto": posto, **k})
            ev("vista_pagina", pagina="/")
            for _ in range(rnd.choices([1, 2, 3], [6, 3, 1])[0]):
                escrita = rnd.randint(2000, 15000)
                t += escrita
                pid = uuid.uuid4().hex
                if rnd.random() < 0.18:
                    termo = rnd.choice(NAO_EXISTEM)
                    ev("pesquisa", termo=termo, num_resultados=0, pesquisa_id=pid, duracao_ms=escrita)
                    if rnd.random() < 0.3:
                        t += 4000
                        ev("nao_encontrado", termo=termo)
                    continue
                lid, titulo, _ = rnd.choices(LIVROS, pesos)[0]
                termo = rnd.choice(TERMOS_LIVRO[lid])
                ev("pesquisa", termo=termo, num_resultados=rnd.randint(1, 6), pesquisa_id=pid, duracao_ms=escrita)
                if rnd.random() < 0.25:  # viu a lista e desistiu
                    t += rnd.randint(5000, 30000)
                    continue
                escolha = rnd.randint(3000, 25000)
                t += escolha
                ev("clique_resultado", livro_id=lid, livro_titulo=titulo, pesquisa_id=pid, termo=termo,
                   posicao=rnd.choices([1, 2, 3, 4], [6, 3, 1, 1])[0], duracao_ms=escolha)
                ev("vista_livro", livro_id=lid, livro_titulo=titulo)
                if rnd.random() < 0.65:
                    minutos = rnd.expovariate(1 / 14)
                    restante = int(minutos * 60000)
                    while restante > 0 and t < agora:
                        bloco = min(60000, restante)
                        t += bloco
                        ev("leitura", livro_id=lid, livro_titulo=titulo, duracao_ms=bloco)
                        restante -= bloco
                    break
            if posto:  # sinal de presença a cada minuto enquanto o computador é usado
                for tp in range(t0, min(t, agora) + 1, 60000):
                    eventos.append({"tipo": "presenca", "ts": tp, "sessao": s, "utilizador": u,
                                    "posto": posto, "duracao_ms": 0 if tp == t0 else 60000})
    # alguns computadores em uso neste momento
    for posto in POSTOS[:5]:
        s = uuid.uuid4().hex
        for m in range(rnd.randint(3, 20), -1, -1):
            eventos.append({"tipo": "presenca", "ts": agora - m * 60000 - rnd.randint(0, 20000), "sessao": s,
                            "utilizador": None, "posto": posto, "duracao_ms": 60000})
    eventos = [e for e in eventos if e["ts"] <= agora]
    # validar_evento substitui ts muito antigos (> 7 dias) pela hora de receção;
    # aqui validamos cada evento como se tivesse chegado no seu próprio instante.
    conn.executemany(
        f"INSERT INTO eventos ({', '.join(analytics.COLUNAS)}) VALUES ({', '.join('?' * len(analytics.COLUNAS))})",
        [tuple(v[c] for c in analytics.COLUNAS) for v in
         (analytics.validar_evento(e, agora_ms=e["ts"]) for e in eventos) if v],
    )
    conn.commit()
    return len(eventos)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dias", type=int, default=90)
    ap.add_argument("--sessoes", type=int, default=40, help="sessões por dia útil (média)")
    ap.add_argument("--bd", default=None)
    ap.add_argument("--semente", type=int, default=7)
    a = ap.parse_args()
    conn = analytics.ligar(a.bd)
    n = gerar(conn, a.dias, a.sessoes, a.semente)
    print(f"{n} eventos de demonstração gravados.")


if __name__ == "__main__":
    main()
