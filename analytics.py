"""Núcleo de recolha e cálculo de métricas da Biblioteca Virtual.

Só usa a biblioteca padrão do Python (sqlite3). Todos os instantes são
guardados em milissegundos UTC; o agrupamento por dia/semana/mês é feito no
fuso horário configurado (por omissão UTC+1, hora de Angola).
"""

from __future__ import annotations

import os
import sqlite3
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone

TIPOS_EVENTO = {
    "vista_pagina",      # abertura de qualquer página da biblioteca
    "pesquisa",          # pesquisa submetida: termo, num_resultados, duracao_ms (tempo a escrever)
    "clique_resultado",  # clique num resultado: pesquisa_id, livro, posicao, duracao_ms (desde a submissão)
    "vista_livro",       # abertura da ficha de um livro
    "leitura",           # bloco de tempo de leitura ativa: livro, duracao_ms
    "nao_encontrado",    # livro pedido/inexistente (pedido explícito ou link partido)
    "presenca",          # sinal periódico do computador: duracao_ms = tempo de uso ativo desde o último sinal
}

SEM_POSTO = "__sem_posto__"            # valor do filtro para acessos sem computador identificado
ONLINE_MS = 3 * 60 * 1000              # computador "ativo agora" se deu sinal nos últimos 3 min
MAX_PRESENCA_MS = 5 * 60 * 1000

MAX_TEXTO = 300
MAX_LEITURA_BLOCO_MS = 5 * 60 * 1000       # um bloco de leitura nunca vale mais de 5 min
MAX_DURACAO_PESQUISA_MS = 30 * 60 * 1000   # pesquisas acima de 30 min são ruído
TOLERANCIA_PASSADO_MS = 7 * 24 * 3600 * 1000  # eventos atrasados até 7 dias são aceites
TOLERANCIA_FUTURO_MS = 3600 * 1000           # relógio do cliente adiantado até 1 h

AGRUPAMENTOS = ("dia", "semana", "mes")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS eventos (
    id             INTEGER PRIMARY KEY,
    ts             INTEGER NOT NULL,
    recebido       INTEGER NOT NULL,
    tipo           TEXT    NOT NULL,
    sessao         TEXT    NOT NULL,
    utilizador     TEXT,
    pagina         TEXT,
    termo          TEXT,
    termo_norm     TEXT,
    num_resultados INTEGER,
    pesquisa_id    TEXT,
    livro_id       TEXT,
    livro_titulo   TEXT,
    posicao        INTEGER,
    duracao_ms     INTEGER,
    posto          TEXT
);
CREATE INDEX IF NOT EXISTS idx_eventos_tipo_ts ON eventos (tipo, ts);
CREATE INDEX IF NOT EXISTS idx_eventos_ts ON eventos (ts);
CREATE INDEX IF NOT EXISTS idx_eventos_pesquisa ON eventos (pesquisa_id);
"""
INDICES_POSTO = "CREATE INDEX IF NOT EXISTS idx_eventos_posto_ts ON eventos (posto, ts);"

# Catálogo: o melhor título conhecido de cada livro. A qualidade indica de onde veio o título,
# para um título melhor substituir um pior, mas nunca o contrário:
#   9 corrigido à mão no painel   5 dados estruturados da página (JSON-LD)
#   4 meta og:title               3 título do separador       2 cabeçalho / capa / atributos
#   1 texto do link               0 deduzido do endereço (sem acentos)
QUALIDADE_MANUAL = 9
ESQUEMA_LIVROS = """
CREATE TABLE IF NOT EXISTS livros (
    livro_id   TEXT PRIMARY KEY,
    titulo     TEXT NOT NULL,
    autor      TEXT,
    isbn       TEXT,
    qualidade  INTEGER NOT NULL DEFAULT 0,
    atualizado INTEGER NOT NULL
);
"""


# --------------------------------------------------------------------------- BD

def ligar(caminho: str | None = None) -> sqlite3.Connection:
    caminho = caminho or os.environ.get("BIBLIO_BD", "biblioteca_analytics.db")
    conn = sqlite3.connect(caminho, timeout=10)
    conn.row_factory = sqlite3.Row
    if caminho != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(ESQUEMA)
    # migração de bases criadas pela versão anterior (sem a coluna posto)
    if "posto" not in {r[1] for r in conn.execute("PRAGMA table_info(eventos)")}:
        conn.execute("ALTER TABLE eventos ADD COLUMN posto TEXT")
    conn.execute(INDICES_POSTO)
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='livros'").fetchone():
        conn.executescript(ESQUEMA_LIVROS)
        _preencher_catalogo(conn)
    conn.commit()
    return conn


def _preencher_catalogo(conn: sqlite3.Connection) -> None:
    """Na primeira vez, cria o catálogo a partir dos eventos já gravados
    (o título limpo mais frequente de cada livro)."""
    contagem: dict[str, dict[str, int]] = {}
    for livro_id, titulo, n in conn.execute(
            "SELECT livro_id, livro_titulo, COUNT(*) FROM eventos WHERE livro_id IS NOT NULL "
            "AND livro_titulo IS NOT NULL GROUP BY livro_id, livro_titulo"):
        t = limpar_titulo(titulo)
        if t:
            contagem.setdefault(livro_id, {}).setdefault(t, 0)
            contagem[livro_id][t] += n
    agora = int(time.time() * 1000)
    conn.executemany("INSERT OR IGNORE INTO livros (livro_id, titulo, qualidade, atualizado) VALUES (?, ?, 1, ?)",
                     [(i, max(ts, key=ts.get), agora) for i, ts in contagem.items()])


# ------------------------------------------------------------------- validação

def normalizar_termo(termo: str) -> str:
    """'  Pepetela ' e 'pépetela' agrupam-se como o mesmo termo."""
    sem_acentos = unicodedata.normalize("NFKD", termo)
    sem_acentos = "".join(c for c in sem_acentos if not unicodedata.combining(c))
    return " ".join(sem_acentos.lower().split())


_GENERICOS = {"perlego", "search", "pesquisa", "reader", "leitor", "home", "início", "inicio", "loading",
              "loading...", "a carregar", "read", "read now", "ler", "ler agora", "start reading", "continue reading",
              "book", "livro", "ebook", "pdf", "epub", "untitled", "sem título", "contents", "índice",
              "table of contents", "cover", "capa", "my library", "a minha biblioteca"}


def limpar_titulo(titulo, autor: str | None = None) -> str | None:
    """Tira do título o que não é título: '| Perlego', '[PDF]', 'Read online', 'by Autor',
    espaços repetidos. Devolve None para textos genéricos ('Perlego', 'Read now', 'Chapter 3'…)."""
    import re
    if not titulo:
        return None
    t = " ".join(str(titulo).replace("\u00a0", " ").split())
    t = re.sub(r"\s*[|–—-]\s*Perlego\b.*$", "", t, flags=re.I)
    t = re.sub(r"^Perlego\s*[|–—:-]\s*", "", t, flags=re.I)
    formato = r"(?:pdf|epub|e-?book|kindle|mobi)"
    for _ in range(3):  # sufixos podem vir encadeados: "Mayombe [PDF] - Read online"
        antes = t
        t = re.sub(r"\s*[-–—|:]?\s*(?:read|ler|leia)\s+(?:online|now|agora|free|grátis)\b.*$", "", t, flags=re.I)
        t = re.sub(rf"\s*[-–—|:]?\s*[\[(]?\s*{formato}(?:\s*(?:and|&|e|/|,)\s*{formato})*\s*[\])]?\s*$", "", t, flags=re.I)
        t = re.sub(r"\s*[-–—|:]\s*$", "", t)
        if t == antes:
            break
    if autor:
        t = re.sub(rf"\s+(?:by|de|por|-|–|—)\s+{re.escape(autor.strip())}\s*$", "", t, flags=re.I)
    t = t.strip(" \"'“”‘’«»")
    if len(t) < 2 or t.lower() in _GENERICOS:
        return None
    if re.fullmatch(r"(?:chapter|cap[ií]tulo|part|parte|section|secção|page|página)\s*[\divxlc.]+.*", t, flags=re.I) \
            and len(t) < 40:
        return None
    if re.fullmatch(r"[\W_]+", t):  # só símbolos
        return None
    return t[:MAX_TEXTO]


def limpar_isbn(valor) -> str | None:
    import re
    if not valor:
        return None
    digitos = re.sub(r"[^0-9Xx]", "", str(valor)).upper()
    return digitos if len(digitos) in (10, 13) else None


def _texto(valor, limite=MAX_TEXTO):
    if valor is None:
        return None
    valor = str(valor).strip()
    return valor[:limite] or None


def _inteiro(valor, minimo=None, maximo=None):
    if valor is None or isinstance(valor, bool):
        return None
    try:
        n = int(float(valor))
    except (TypeError, ValueError):
        return None
    if minimo is not None:
        n = max(minimo, n)
    if maximo is not None:
        n = min(maximo, n)
    return n


def validar_evento(bruto: dict, agora_ms: int | None = None) -> dict | None:
    """Limpa um evento vindo do cliente. Devolve None se for inválido."""
    if not isinstance(bruto, dict):
        return None
    agora_ms = agora_ms if agora_ms is not None else int(time.time() * 1000)
    tipo = _texto(bruto.get("tipo"), 40)
    sessao = _texto(bruto.get("sessao"), 80)
    if tipo not in TIPOS_EVENTO or not sessao:
        return None

    ts = _inteiro(bruto.get("ts"))
    if ts is None or ts < agora_ms - TOLERANCIA_PASSADO_MS or ts > agora_ms + TOLERANCIA_FUTURO_MS:
        ts = agora_ms

    termo = _texto(bruto.get("termo"))
    ev = {
        "ts": ts,
        "recebido": agora_ms,
        "tipo": tipo,
        "sessao": sessao,
        "utilizador": _texto(bruto.get("utilizador"), 80),
        "pagina": _texto(bruto.get("pagina")),
        "termo": termo,
        "termo_norm": normalizar_termo(termo) if termo else None,
        "num_resultados": _inteiro(bruto.get("num_resultados"), 0),
        "pesquisa_id": _texto(bruto.get("pesquisa_id"), 80),
        "livro_id": _texto(bruto.get("livro_id"), 120),
        "livro_titulo": None,
        "posicao": _inteiro(bruto.get("posicao"), 1, 10_000),
        "duracao_ms": None,
        "posto": _texto(bruto.get("posto"), 80),
        # só para o catálogo de livros (não ficam na tabela de eventos)
        "livro_autor": _texto(bruto.get("livro_autor"), 200),
        "livro_isbn": limpar_isbn(bruto.get("livro_isbn")),
        "titulo_qualidade": _inteiro(bruto.get("titulo_qualidade"), 0, 5),
    }
    ev["livro_titulo"] = (limpar_titulo(bruto.get("livro_titulo"), ev["livro_autor"]) if tipo != "nao_encontrado"
                          else _texto(bruto.get("livro_titulo")))
    if ev["titulo_qualidade"] is None:
        ev["titulo_qualidade"] = 1
    teto = {"leitura": MAX_LEITURA_BLOCO_MS, "presenca": MAX_PRESENCA_MS}.get(tipo, MAX_DURACAO_PESQUISA_MS)
    ev["duracao_ms"] = _inteiro(bruto.get("duracao_ms"), 0, teto)

    if tipo == "pesquisa" and (not termo or ev["num_resultados"] is None):
        return None
    if tipo in ("leitura", "vista_livro", "clique_resultado") and not ev["livro_id"]:
        return None
    if tipo == "leitura" and not ev["duracao_ms"]:
        return None
    if tipo == "nao_encontrado" and not (termo or ev["livro_titulo"]):
        return None
    return ev


COLUNAS = ("ts", "recebido", "tipo", "sessao", "utilizador", "pagina", "termo",
           "termo_norm", "num_resultados", "pesquisa_id", "livro_id",
           "livro_titulo", "posicao", "duracao_ms", "posto")


def inserir_eventos(conn: sqlite3.Connection, brutos, agora_ms: int | None = None,
                    posto_omissao: str | None = None) -> int:
    """Valida e grava uma lista de eventos. Devolve quantos foram aceites.
    `posto_omissao` identifica o computador quando o evento não traz um (p. ex. pelo IP)."""
    validos = [e for e in (validar_evento(b, agora_ms) for b in brutos) if e]
    if posto_omissao:
        for e in validos:
            e["posto"] = e["posto"] or posto_omissao
    if validos:
        conn.executemany(
            f"INSERT INTO eventos ({', '.join(COLUNAS)}) "
            f"VALUES ({', '.join('?' * len(COLUNAS))})",
            [tuple(e[c] for c in COLUNAS) for e in validos],
        )
        for e in validos:
            if e["livro_id"] and e["livro_titulo"] and e["tipo"] != "nao_encontrado":
                atualizar_livro(conn, e["livro_id"], e["livro_titulo"], e["livro_autor"], e["livro_isbn"],
                                e["titulo_qualidade"], commit=False)
        conn.commit()
    return len(validos)


def atualizar_livro(conn: sqlite3.Connection, livro_id: str, titulo: str, autor: str | None = None,
                    isbn: str | None = None, qualidade: int = 1, commit: bool = True) -> None:
    """Guarda o título no catálogo se for melhor (ou igual e mais recente) do que o conhecido.
    Autor e ISBN preenchem-se sempre que ainda faltem. Um título corrigido à mão nunca é substituído
    automaticamente."""
    agora = int(time.time() * 1000)
    conn.execute("""
        INSERT INTO livros (livro_id, titulo, autor, isbn, qualidade, atualizado) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(livro_id) DO UPDATE SET
            titulo = CASE WHEN excluded.qualidade >= livros.qualidade
                           AND (livros.qualidade < 9 OR excluded.qualidade >= 9)
                          THEN excluded.titulo ELSE livros.titulo END,
            qualidade = MAX(livros.qualidade, excluded.qualidade),
            autor = CASE WHEN excluded.qualidade >= 9 THEN COALESCE(excluded.autor, livros.autor)
                         ELSE COALESCE(livros.autor, excluded.autor) END,
            isbn = COALESCE(livros.isbn, excluded.isbn),
            atualizado = excluded.atualizado""",
                 (livro_id, titulo, autor, isbn, qualidade, agora))
    if commit:
        conn.commit()


def corrigir_livro(conn: sqlite3.Connection, livro_id: str, titulo: str, autor: str | None = None) -> dict:
    """Correção manual feita no painel: passa a valer sobre qualquer título detetado."""
    livro_id = _texto(livro_id, 120)
    t = " ".join(str(titulo or "").split())[:MAX_TEXTO]
    if not livro_id or len(t) < 2:
        raise ValueError("indique o livro e um título com pelo menos 2 caracteres")
    a = _texto(autor, 200)
    conn.execute("UPDATE livros SET qualidade = 0 WHERE livro_id = ?", (livro_id,))  # permite reescrever
    atualizar_livro(conn, livro_id, t, a, None, QUALIDADE_MANUAL)
    return dict(conn.execute("SELECT * FROM livros WHERE livro_id = ?", (livro_id,)).fetchone())


# --------------------------------------------------------------------- períodos

def _fuso(fuso_horas: float) -> timezone:
    return timezone(timedelta(hours=fuso_horas))


def intervalo_periodo(periodo: str = "30d", inicio: str | None = None,
                      fim: str | None = None, fuso_horas: float = 1.0,
                      hoje: date | None = None) -> tuple[date, date]:
    """Converte 'hoje' | '7d' | '30d' | '90d' | '12m' ou datas ISO num intervalo
    de dias locais [inicio, fim] (ambos incluídos)."""
    hoje = hoje or datetime.now(_fuso(fuso_horas)).date()
    if inicio or fim:
        d_ini = date.fromisoformat(inicio) if inicio else hoje - timedelta(days=29)
        d_fim = date.fromisoformat(fim) if fim else hoje
    else:
        dias = {"hoje": 1, "7d": 7, "30d": 30, "90d": 90, "12m": 365}.get(periodo)
        if dias is None:
            raise ValueError(f"período desconhecido: {periodo}")
        d_ini, d_fim = hoje - timedelta(days=dias - 1), hoje
    if d_ini > d_fim:
        d_ini, d_fim = d_fim, d_ini
    return d_ini, d_fim


def _limites_ms(d_ini: date, d_fim: date, fuso_horas: float) -> tuple[int, int]:
    tz = _fuso(fuso_horas)
    a = datetime(d_ini.year, d_ini.month, d_ini.day, tzinfo=tz)
    b = datetime(d_fim.year, d_fim.month, d_fim.day, tzinfo=tz) + timedelta(days=1)
    return int(a.timestamp() * 1000), int(b.timestamp() * 1000)


def _chave_balde(d: date, agrupar: str) -> str:
    if agrupar == "dia":
        return d.isoformat()
    if agrupar == "semana":
        return (d - timedelta(days=d.weekday())).isoformat()  # segunda-feira
    return d.strftime("%Y-%m")


def _baldes(d_ini: date, d_fim: date, agrupar: str) -> list[str]:
    chaves, d = [], d_ini
    while d <= d_fim:
        k = _chave_balde(d, agrupar)
        if not chaves or chaves[-1] != k:
            chaves.append(k)
        d += timedelta(days=1)
    return chaves


def _expr_balde(agrupar: str) -> str:
    # ? = modificador do fuso, p. ex. '+1 hours'
    if agrupar == "dia":
        return "date(ts / 1000, 'unixepoch', ?)"
    if agrupar == "semana":
        return "date(ts / 1000, 'unixepoch', ?, 'weekday 0', '-6 days')"
    return "strftime('%Y-%m', ts / 1000, 'unixepoch', ?)"


# --------------------------------------------------------------------- métricas

def _r(valor, casas=1):
    return None if valor is None else round(valor, casas)


def _taxa(parte, total):
    return None if not total else round(100.0 * parte / total, 1)


def metricas(conn: sqlite3.Connection, periodo: str = "30d", inicio: str | None = None,
             fim: str | None = None, agrupar: str = "dia", fuso_horas: float = 1.0,
             limite: int = 10, hoje: date | None = None, posto: str | None = None,
             agora_ms: int | None = None) -> dict:
    if agrupar not in AGRUPAMENTOS:
        raise ValueError(f"agrupamento desconhecido: {agrupar}")
    d_ini, d_fim = intervalo_periodo(periodo, inicio, fim, fuso_horas, hoje)
    a, b = _limites_ms(d_ini, d_fim, fuso_horas)
    mod = f"{fuso_horas:+g} hours"
    janela = "ts >= :a AND ts < :b"
    if posto == SEM_POSTO:
        janela += " AND posto IS NULL"
    elif posto:
        janela += " AND posto = :posto"
    p = {"a": a, "b": b, "lim": limite, "posto": posto}
    # as métricas de navegação ignoram os sinais de presença dos computadores
    nav = f"{janela} AND tipo != 'presenca'"

    def um(sql, **extra):
        return conn.execute(sql, {**p, **extra}).fetchone()

    def todos(sql, **extra):
        return [dict(r) for r in conn.execute(sql, {**p, **extra}).fetchall()]

    # Pesquisas com sucesso = pesquisas que tiveram pelo menos um clique num resultado.
    pesquisas_cte = f"""
        WITH cliques AS (
            SELECT pesquisa_id, MIN(duracao_ms) AS ate_clique, MIN(posicao) AS posicao
            FROM eventos WHERE tipo = 'clique_resultado' AND pesquisa_id IS NOT NULL
              AND ts >= :a AND ts < :b + 3600000
            GROUP BY pesquisa_id
        ),
        p AS (
            SELECT e.*, c.pesquisa_id IS NOT NULL AS sucesso, c.ate_clique, c.posicao AS pos_clique
            FROM eventos e LEFT JOIN cliques c ON c.pesquisa_id = e.pesquisa_id
            WHERE e.tipo = 'pesquisa' AND e.{janela.replace(" AND ", " AND e.")}
        )
    """

    geral = um(f"""SELECT COUNT(DISTINCT sessao) AS sessoes,
                          COUNT(DISTINCT COALESCE(utilizador, sessao)) AS utilizadores,
                          SUM(tipo = 'vista_pagina') AS vistas_pagina,
                          SUM(tipo = 'vista_livro') AS vistas_livro
                   FROM eventos WHERE {nav}""")
    pq = um(pesquisas_cte + """
        SELECT COUNT(*) AS total,
               SUM(num_resultados = 0) AS sem_resultados,
               SUM(sucesso) AS com_sucesso,
               SUM(num_resultados > 0 AND NOT sucesso) AS sem_clique,
               AVG(duracao_ms) AS escrita_ms,
               AVG(ate_clique) AS ate_clique_ms,
               AVG(COALESCE(duracao_ms, 0) + ate_clique) AS total_ms,
               AVG(pos_clique) AS posicao_media,
               COUNT(DISTINCT sessao) AS sessoes_com_pesquisa
        FROM p""")
    lt = um(f"""SELECT SUM(duracao_ms) AS ms,
                       COUNT(DISTINCT COALESCE(utilizador, sessao)) AS leitores,
                       COUNT(DISTINCT livro_id) AS livros
                FROM eventos WHERE tipo = 'leitura' AND {janela}""")
    duracao_sessao = um(f"""SELECT AVG(fim - ini) AS ms FROM (
                              SELECT MIN(ts) AS ini, MAX(ts) AS fim FROM eventos
                              WHERE {nav} GROUP BY sessao HAVING COUNT(*) > 1)""")
    nao_enc_explicitos = um(f"""SELECT COUNT(*) AS n FROM eventos
                                WHERE tipo = 'nao_encontrado' AND {janela}""")["n"]

    total_pq = pq["total"] or 0
    min_leitura = (lt["ms"] or 0) / 60000
    resumo = {
        "sessoes": geral["sessoes"] or 0,
        "utilizadores": geral["utilizadores"] or 0,
        "vistas_pagina": geral["vistas_pagina"] or 0,
        "vistas_livro": geral["vistas_livro"] or 0,
        "duracao_media_sessao_min": _r((duracao_sessao["ms"] or 0) / 60000 if duracao_sessao["ms"] else None),
        "pesquisas": total_pq,
        "pesquisas_por_sessao": _r(total_pq / pq["sessoes_com_pesquisa"]) if pq["sessoes_com_pesquisa"] else None,
        "taxa_sucesso_pesquisa": _taxa(pq["com_sucesso"] or 0, total_pq),
        "taxa_sem_resultados": _taxa(pq["sem_resultados"] or 0, total_pq),
        "taxa_abandono_pesquisa": _taxa(pq["sem_clique"] or 0, total_pq),
        "tempo_medio_escrita_pesquisa_s": _r(pq["escrita_ms"] / 1000 if pq["escrita_ms"] is not None else None),
        "tempo_medio_ate_encontrar_s": _r(pq["ate_clique_ms"] / 1000 if pq["ate_clique_ms"] is not None else None),
        "tempo_medio_pesquisa_total_s": _r(pq["total_ms"] / 1000 if pq["total_ms"] is not None else None),
        "posicao_media_clique": _r(pq["posicao_media"]),
        "pedidos_nao_encontrados": nao_enc_explicitos,
        "tempo_leitura_total_min": _r(min_leitura),
        "leitores": lt["leitores"] or 0,
        "livros_lidos": lt["livros"] or 0,
        "tempo_leitura_medio_por_leitor_min": _r(min_leitura / lt["leitores"]) if lt["leitores"] else None,
    }

    termos = todos(pesquisas_cte + """
        SELECT MIN(termo) AS termo, COUNT(*) AS pesquisas,
               COUNT(DISTINCT COALESCE(utilizador, sessao)) AS utilizadores,
               ROUND(100.0 * SUM(sucesso) / COUNT(*), 1) AS taxa_sucesso,
               ROUND(AVG(num_resultados), 1) AS resultados_medios
        FROM p GROUP BY termo_norm ORDER BY pesquisas DESC, termo LIMIT :lim""")

    livros_procurados = todos(f"""
        SELECT e.livro_id, COALESCE(MAX(l.titulo), MAX(e.livro_titulo)) AS titulo,
               MAX(l.autor) AS autor, MAX(l.isbn) AS isbn,
               SUM(e.tipo = 'vista_livro') AS vistas,
               SUM(e.tipo = 'clique_resultado') AS cliques_pesquisa,
               COUNT(DISTINCT COALESCE(e.utilizador, e.sessao)) AS utilizadores
        FROM eventos e LEFT JOIN livros l ON l.livro_id = e.livro_id
        WHERE e.tipo IN ('vista_livro', 'clique_resultado') AND e.{janela.replace(" AND ", " AND e.")}
        GROUP BY e.livro_id ORDER BY vistas + cliques_pesquisa DESC, titulo LIMIT :lim""")

    mais_lidos = todos(f"""
        SELECT e.livro_id, COALESCE(MAX(l.titulo), MAX(e.livro_titulo)) AS titulo,
               MAX(l.autor) AS autor, MAX(l.isbn) AS isbn,
               ROUND(SUM(e.duracao_ms) / 60000.0, 1) AS minutos,
               COUNT(DISTINCT COALESCE(e.utilizador, e.sessao)) AS leitores,
               COUNT(DISTINCT e.sessao) AS sessoes_leitura
        FROM eventos e LEFT JOIN livros l ON l.livro_id = e.livro_id
        WHERE e.tipo = 'leitura' AND e.{janela.replace(" AND ", " AND e.")}
        GROUP BY e.livro_id ORDER BY minutos DESC, titulo LIMIT :lim""")

    nao_encontrados = todos(f"""
        SELECT MIN(COALESCE(termo, livro_titulo)) AS termo, COUNT(*) AS vezes,
               COUNT(DISTINCT COALESCE(utilizador, sessao)) AS utilizadores,
               SUM(tipo = 'nao_encontrado') AS pedidos_explicitos,
               MAX(ts) AS ultima_vez_ms
        FROM eventos
        WHERE {janela} AND ((tipo = 'pesquisa' AND num_resultados = 0) OR tipo = 'nao_encontrado')
        GROUP BY COALESCE(termo_norm, lower(livro_titulo))
        ORDER BY vezes DESC, termo LIMIT :lim""")
    for linha in nao_encontrados:
        linha["ultima_vez"] = datetime.fromtimestamp(
            linha.pop("ultima_vez_ms") / 1000, _fuso(fuso_horas)).strftime("%Y-%m-%d %H:%M")

    # Série temporal (dia / semana / mês) com baldes vazios preenchidos.
    balde = _expr_balde(agrupar)
    serie = {k: {"periodo": k, "sessoes": 0, "pesquisas": 0, "com_sucesso": 0, "sem_clique": 0,
                 "sem_resultados": 0, "tempo_medio_pesquisa_s": None, "minutos_leitura": 0.0,
                 "leitores": 0} for k in _baldes(d_ini, d_fim, agrupar)}
    for r in todos(f"SELECT {balde.replace('?', ':mod')} AS k, COUNT(DISTINCT sessao) AS s "
                   f"FROM eventos WHERE {nav} GROUP BY k", mod=mod):
        if r["k"] in serie:
            serie[r["k"]]["sessoes"] = r["s"]
    for r in todos(pesquisas_cte + f"""
            SELECT {balde.replace('?', ':mod')} AS k, COUNT(*) AS n, SUM(sucesso) AS ok,
                   SUM(num_resultados > 0 AND NOT sucesso) AS sc, SUM(num_resultados = 0) AS z,
                   AVG(COALESCE(duracao_ms, 0) + ate_clique) AS t
            FROM p GROUP BY k""", mod=mod):
        if r["k"] in serie:
            serie[r["k"]].update(pesquisas=r["n"], com_sucesso=r["ok"] or 0, sem_clique=r["sc"] or 0,
                                 sem_resultados=r["z"] or 0,
                                 tempo_medio_pesquisa_s=_r(r["t"] / 1000) if r["t"] is not None else None)
    for r in todos(f"""SELECT {balde.replace('?', ':mod')} AS k, SUM(duracao_ms) AS ms,
                              COUNT(DISTINCT COALESCE(utilizador, sessao)) AS l
                       FROM eventos WHERE tipo = 'leitura' AND {janela} GROUP BY k""", mod=mod):
        if r["k"] in serie:
            serie[r["k"]].update(minutos_leitura=_r(r["ms"] / 60000), leitores=r["l"])

    por_hora = [{"hora": h, "pesquisas": 0, "minutos_leitura": 0.0} for h in range(24)]
    for r in todos(f"""SELECT CAST(strftime('%H', ts / 1000, 'unixepoch', :mod) AS INTEGER) AS h,
                              SUM(tipo = 'pesquisa') AS pq,
                              SUM(CASE WHEN tipo = 'leitura' THEN duracao_ms ELSE 0 END) AS ms
                       FROM eventos WHERE {janela} GROUP BY h""", mod=mod):
        por_hora[r["h"]].update(pesquisas=r["pq"] or 0, minutos_leitura=_r((r["ms"] or 0) / 60000))

    return {
        "intervalo": {"inicio": d_ini.isoformat(), "fim": d_fim.isoformat(),
                      "agrupar": agrupar, "fuso_horas": fuso_horas, "posto": posto},
        "computadores": computadores(conn, a, b, posto, fuso_horas, agora_ms),
        "perlego_counter": metricas_counter(conn, d_ini, d_fim, limite),
        "resumo": resumo,
        "mais_procurados_termos": termos,
        "mais_procurados_livros": livros_procurados,
        "mais_lidos": mais_lidos,
        "nao_encontrados": nao_encontrados,
        "serie": list(serie.values()),
        "por_hora": por_hora,
    }


def computadores(conn: sqlite3.Connection, a: int, b: int, posto: str | None = None,
                 fuso_horas: float = 1.0, agora_ms: int | None = None) -> list[dict]:
    """Uma linha por computador: estado agora e uso no intervalo [a, b[.
    Acessos sem computador identificado (p. ex. a partir de casa) aparecem como posto None."""
    agora_ms = agora_ms if agora_ms is not None else int(time.time() * 1000)
    filtro = ""
    if posto == SEM_POSTO:
        filtro = "AND posto IS NULL"
    elif posto:
        filtro = "AND posto = :posto"
    linhas = [dict(r) for r in conn.execute(f"""
        WITH cliques AS (SELECT DISTINCT pesquisa_id FROM eventos
                         WHERE tipo = 'clique_resultado' AND pesquisa_id IS NOT NULL AND ts >= :a)
        SELECT posto,
               COUNT(DISTINCT CASE WHEN tipo != 'presenca' THEN sessao END) AS sessoes,
               COUNT(DISTINCT CASE WHEN tipo != 'presenca' THEN COALESCE(utilizador, sessao) END) AS utilizadores,
               SUM(tipo = 'pesquisa') AS pesquisas,
               ROUND(100.0 * SUM(tipo = 'pesquisa' AND pesquisa_id IN (SELECT pesquisa_id FROM cliques))
                     / NULLIF(SUM(tipo = 'pesquisa'), 0), 1) AS taxa_sucesso,
               SUM((tipo = 'pesquisa' AND num_resultados = 0) OR tipo = 'nao_encontrado') AS nao_encontrados,
               ROUND(SUM(CASE WHEN tipo = 'leitura' THEN duracao_ms ELSE 0 END) / 60000.0, 1) AS minutos_leitura,
               ROUND(SUM(CASE WHEN tipo = 'presenca' THEN duracao_ms ELSE 0 END) / 3600000.0, 1) AS horas_uso
        FROM eventos WHERE ts >= :a AND ts < :b {filtro}
        GROUP BY posto""", {"a": a, "b": b, "posto": posto})]
    ultimos = {r["posto"]: r["u"] for r in conn.execute(
        f"SELECT posto, MAX(ts) AS u FROM eventos WHERE ts <= :agora {filtro} GROUP BY posto",
        {"agora": agora_ms + TOLERANCIA_FUTURO_MS, "posto": posto})}
    vistos = {r["posto"] for r in linhas}
    # computadores conhecidos mas sem uso no período também aparecem (com zeros)
    for nome in ultimos:
        if nome not in vistos:
            linhas.append({"posto": nome, "sessoes": 0, "utilizadores": 0, "pesquisas": 0, "taxa_sucesso": None,
                           "nao_encontrados": 0, "minutos_leitura": 0.0, "horas_uso": 0.0})
    tz = _fuso(fuso_horas)
    for r in linhas:
        u = ultimos.get(r["posto"])
        r["ultima_atividade"] = datetime.fromtimestamp(u / 1000, tz).strftime("%Y-%m-%d %H:%M") if u else None
        r["minutos_sem_atividade"] = None if u is None else max(0, (agora_ms - u) // 60000)
        r["ativo_agora"] = r["posto"] is not None and u is not None and agora_ms - u <= ONLINE_MS
    linhas.sort(key=lambda r: (r["posto"] is None, r["posto"] or ""))
    return linhas


def lista_postos(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT posto FROM eventos WHERE posto IS NOT NULL ORDER BY posto")]


TABELAS_EXPORTAVEIS = ("perlego_counter", "computadores", "mais_procurados_termos", "mais_procurados_livros", "mais_lidos",
                       "nao_encontrados", "serie", "por_hora", "resumo")


def para_csv(dados: dict, tabela: str) -> str:
    import csv
    import io
    if tabela not in TABELAS_EXPORTAVEIS:
        raise ValueError(f"tabela desconhecida: {tabela}")
    linhas = dados[tabela]
    if tabela == "perlego_counter":
        linhas = linhas.get("mais_lidos", [])
    if tabela == "resumo":
        linhas = [{"metrica": k, "valor": v} for k, v in linhas.items()]
    buf = io.StringIO()
    if linhas:
        w = csv.DictWriter(buf, fieldnames=list(linhas[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(linhas)
    return buf.getvalue()


# ======================================================= relatórios COUNTER (Perlego)
# A Perlego (e outras plataformas) disponibilizam relatórios COUNTER 5/5.1 — p. ex. TR_B1
# "Book Requests" — com métricas mensais por título (Total_Item_Requests, Unique_Title_Requests).
# Aceitamos o formato tabular em CSV, TSV ou XLSX.

ESQUEMA_COUNTER = """
CREATE TABLE IF NOT EXISTS counter (
    relatorio  TEXT NOT NULL,
    titulo     TEXT NOT NULL,
    editor     TEXT,
    isbn       TEXT NOT NULL DEFAULT '',
    metrica    TEXT NOT NULL,
    mes        TEXT NOT NULL,          -- AAAA-MM
    valor      INTEGER NOT NULL,
    importado  INTEGER NOT NULL,
    PRIMARY KEY (relatorio, titulo, isbn, metrica, mes)
);
"""

_MESES_EN = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _mes_coluna(nome: str) -> str | None:
    """'Jan-2026' / 'jan 2026' / '2026-01' → '2026-01'."""
    import re
    nome = (nome or "").strip()
    m = re.fullmatch(r"([A-Za-z]{3})[-\s](\d{4})", nome)
    if m and m.group(1).lower() in _MESES_EN:
        return f"{m.group(2)}-{_MESES_EN[m.group(1).lower()]:02d}"
    m = re.fullmatch(r"(\d{4})-(\d{2})(?:-\d{2})?", nome)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(1)}-{m.group(2)}"
    return None


def _linhas_xlsx(conteudo: bytes) -> list[list[str]]:
    """Lê a primeira folha de um .xlsx só com a biblioteca padrão."""
    import io
    import re
    import zipfile
    from xml.etree import ElementTree as ET
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
        partilhadas = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("s:si", ns):
                partilhadas.append("".join(t.text or "" for t in si.iter(f"{{{ns['s']}}}t")))
        folhas = sorted(n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
        if not folhas:
            raise ValueError("o ficheiro XLSX não tem folhas")
        raiz = ET.fromstring(z.read(folhas[0]))
    linhas = []
    for row in raiz.iter(f"{{{ns['s']}}}row"):
        valores: dict[int, str] = {}
        for c in row.findall("s:c", ns):
            ref = c.get("r", "")
            letras = re.match(r"[A-Z]+", ref)
            col = 0
            for ch in (letras.group(0) if letras else ""):
                col = col * 26 + ord(ch) - 64
            col = (col - 1) if col else len(valores)
            tipo = c.get("t")
            if tipo == "inlineStr":
                v = "".join(t.text or "" for t in c.iter(f"{{{ns['s']}}}t"))
            else:
                el = c.find("s:v", ns)
                v = el.text if el is not None and el.text is not None else ""
                if tipo == "s" and v:
                    v = partilhadas[int(v)]
            valores[col] = v
        if valores:
            linhas.append([valores.get(i, "") for i in range(max(valores) + 1)])
    return linhas


def _linhas_texto(conteudo: bytes) -> list[list[str]]:
    import csv
    import io
    for cod in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            texto = conteudo.decode(cod)
            break
        except UnicodeDecodeError:
            continue
    amostra = texto[:5000]
    sep = max(("\t", ";", ","), key=amostra.count)
    return [linha for linha in csv.reader(io.StringIO(texto), delimiter=sep)]


def ler_counter(conteudo: bytes) -> dict:
    """Interpreta um relatório COUNTER tabular. Devolve {relatorio, registos: [...]}"""
    linhas = _linhas_xlsx(conteudo) if conteudo[:2] == b"PK" else _linhas_texto(conteudo)
    relatorio = "desconhecido"
    cab = None
    for i, linha in enumerate(linhas):
        celulas = [c.strip() for c in linha]
        if celulas and celulas[0] == "Report_ID" and len(celulas) > 1 and celulas[1]:
            relatorio = celulas[1]
        if "Metric_Type" in celulas and any(c in celulas for c in ("Title", "Platform", "Database", "Item")):
            cab = i
            break
    if cab is None:
        raise ValueError("não parece um relatório COUNTER: falta a linha de cabeçalho com 'Metric_Type'")
    nomes = [c.strip() for c in linhas[cab]]
    col_titulo = next(nomes.index(c) for c in ("Title", "Item", "Database", "Platform") if c in nomes)
    col_metrica = nomes.index("Metric_Type")
    col_editor = nomes.index("Publisher") if "Publisher" in nomes else None
    col_isbn = nomes.index("ISBN") if "ISBN" in nomes else None
    meses = [(i, _mes_coluna(n)) for i, n in enumerate(nomes) if _mes_coluna(n)]
    if not meses:
        raise ValueError("o relatório não tem colunas mensais (ex.: 'Jan-2026'); "
                         "descarregue-o sem a opção Exclude_Monthly_Details")
    registos = []
    for linha in linhas[cab + 1:]:
        if len(linha) <= col_metrica or not linha[col_titulo].strip():
            continue
        for i, mes in meses:
            bruto = linha[i].strip().replace(" ", "") if i < len(linha) else ""
            if not bruto:
                continue
            try:
                valor = int(float(bruto.replace(",", ".")))
            except ValueError:
                continue
            registos.append({
                "titulo": linha[col_titulo].strip()[:MAX_TEXTO],
                "editor": (linha[col_editor].strip()[:MAX_TEXTO] or None) if col_editor is not None and col_editor < len(linha) else None,
                "isbn": linha[col_isbn].strip()[:40] if col_isbn is not None and col_isbn < len(linha) else "",
                "metrica": linha[col_metrica].strip()[:60],
                "mes": mes, "valor": valor,
            })
    return {"relatorio": relatorio, "registos": registos}


def importar_counter(conn: sqlite3.Connection, conteudo: bytes) -> dict:
    dados = ler_counter(conteudo)
    conn.executescript(ESQUEMA_COUNTER)
    agora = int(time.time() * 1000)
    conn.executemany(
        "INSERT OR REPLACE INTO counter (relatorio, titulo, editor, isbn, metrica, mes, valor, importado) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(dados["relatorio"], r["titulo"], r["editor"], r["isbn"], r["metrica"], r["mes"], r["valor"], agora)
         for r in dados["registos"]])
    conn.commit()
    meses = sorted({r["mes"] for r in dados["registos"]})
    return {"relatorio": dados["relatorio"], "registos": len(dados["registos"]),
            "titulos": len({(r["titulo"], r["isbn"]) for r in dados["registos"]}),
            "meses": [meses[0], meses[-1]] if meses else []}


def metricas_counter(conn: sqlite3.Connection, d_ini: date, d_fim: date, limite: int = 10) -> dict:
    """Resumo dos relatórios COUNTER importados para os meses que tocam o intervalo."""
    conn.executescript(ESQUEMA_COUNTER)
    m_ini, m_fim = d_ini.strftime("%Y-%m"), d_fim.strftime("%Y-%m")
    geral = conn.execute("SELECT MIN(mes), MAX(mes), COUNT(*) FROM counter").fetchone()
    if not geral[2]:
        return {"disponivel": False}
    p = {"a": m_ini, "b": m_fim, "lim": limite}
    # TR_B1 tem as duas métricas; outros relatórios podem ter só uma
    pivo = """SUM(CASE WHEN metrica = 'Unique_Title_Requests' THEN valor ELSE 0 END) AS unicos,
              SUM(CASE WHEN metrica = 'Total_Item_Requests' THEN valor ELSE 0 END) AS total,
              SUM(CASE WHEN metrica IN ('No_License', 'Limit_Exceeded') THEN valor ELSE 0 END) AS recusados"""
    titulos = [dict(r) for r in conn.execute(f"""
        SELECT titulo, MAX(editor) AS editor, MAX(isbn) AS isbn, {pivo}
        FROM counter WHERE mes BETWEEN :a AND :b GROUP BY titulo, isbn
        ORDER BY unicos DESC, total DESC, titulo LIMIT :lim""", p)]
    meses = [dict(r) for r in conn.execute(f"""
        SELECT mes AS periodo, {pivo}, COUNT(DISTINCT titulo) AS titulos
        FROM counter WHERE mes BETWEEN :a AND :b GROUP BY mes ORDER BY mes""", p)]
    return {"disponivel": True, "meses_importados": [geral[0], geral[1]],
            "mais_lidos": titulos, "por_mes": meses,
            "total_unicos": sum(m["unicos"] for m in meses), "total_pedidos": sum(m["total"] for m in meses)}
