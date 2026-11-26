"""Servidor de recolha e painel de métricas da Biblioteca Virtual.

Uso:
    python servidor.py                 # http://127.0.0.1:8080
    python servidor.py --porta 9000 --bd dados.db

Variáveis de ambiente opcionais:
    BIBLIO_BD       caminho da base de dados SQLite (por omissão biblioteca_analytics.db)
    BIBLIO_TOKEN    se definido, o painel e a API de métricas exigem ?token=...
    BIBLIO_ORIGENS  origens autorizadas a enviar eventos (CORS), separadas por vírgula; '*' por omissão
    BIBLIO_FUSO     fuso horário em horas para agrupar dias/semanas/meses (por omissão 1 = Angola)
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import analytics

PASTA_ESTATICA = Path(__file__).resolve().parent / "static"
MAX_CORPO = 256 * 1024
MAX_EVENTOS_POR_PEDIDO = 500

FICHEIROS = {
    "/": ("painel.html", "text/html; charset=utf-8", True),
    "/painel": ("painel.html", "text/html; charset=utf-8", True),
    "/tracker.js": ("tracker.js", "application/javascript; charset=utf-8", False),
    "/demo": ("demo.html", "text/html; charset=utf-8", False),
}


class Config:
    bd = os.environ.get("BIBLIO_BD", "biblioteca_analytics.db")
    token = os.environ.get("BIBLIO_TOKEN") or None
    origens = [o.strip() for o in os.environ.get("BIBLIO_ORIGENS", "*").split(",") if o.strip()]
    fuso = float(os.environ.get("BIBLIO_FUSO", "1"))


class Handler(BaseHTTPRequestHandler):
    server_version = "BibliotecaAnalytics/1.0"

    # ------------------------------------------------------------- utilitários
    def log_message(self, fmt, *args):  # registo curto, sem IPs completos
        if os.environ.get("BIBLIO_SILENCIOSO"):
            return
        super().log_message(fmt, *args)

    def _cors(self):
        origem = self.headers.get("Origin")
        if "*" in Config.origens:
            self.send_header("Access-Control-Allow-Origin", "*")
        elif origem and origem in Config.origens:
            self.send_header("Access-Control-Allow-Origin", origem)
            self.send_header("Vary", "Origin")

    def _responder(self, estado, corpo=b"", tipo="application/json; charset=utf-8", extra=None):
        if isinstance(corpo, str):
            corpo = corpo.encode("utf-8")
        self.send_response(estado)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self._cors()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(corpo)

    def _json(self, estado, dados):
        self._responder(estado, json.dumps(dados, ensure_ascii=False))

    def _autorizado(self, qs) -> bool:
        if not Config.token:
            return True
        dado = (qs.get("token") or [""])[0] or self.headers.get("X-Token", "")
        return hmac.compare_digest(dado.encode(), Config.token.encode())

    # ------------------------------------------------------------------ rotas
    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors()
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urlparse(self.path)
        qs = parse_qs(url.query)

        if url.path in FICHEIROS:
            nome, tipo, protegido = FICHEIROS[url.path]
            if protegido and not self._autorizado(qs):
                return self._responder(HTTPStatus.UNAUTHORIZED, "Token em falta ou inválido.",
                                       "text/plain; charset=utf-8")
            return self._responder(HTTPStatus.OK, (PASTA_ESTATICA / nome).read_bytes(), tipo)

        if url.path in ("/api/metricas", "/api/exportar"):
            if not self._autorizado(qs):
                return self._json(HTTPStatus.UNAUTHORIZED, {"erro": "token em falta ou inválido"})
            arg = lambda k, d=None: (qs.get(k) or [d])[0] or d  # noqa: E731
            try:
                conn = analytics.ligar(Config.bd)
                try:
                    dados = analytics.metricas(
                        conn, periodo=arg("periodo", "30d"), inicio=arg("inicio"), fim=arg("fim"),
                        agrupar=arg("agrupar", "dia"), fuso_horas=Config.fuso,
                        limite=max(1, min(100, int(arg("limite", "10")))))
                finally:
                    conn.close()
                if url.path == "/api/metricas":
                    return self._json(HTTPStatus.OK, dados)
                tabela = arg("tabela", "mais_lidos")
                csv_txt = "﻿" + analytics.para_csv(dados, tabela)  # BOM para o Excel abrir acentos
                nome = f"{tabela}_{dados['intervalo']['inicio']}_{dados['intervalo']['fim']}.csv"
                return self._responder(HTTPStatus.OK, csv_txt, "text/csv; charset=utf-8",
                                       {"Content-Disposition": f'attachment; filename="{nome}"'})
            except ValueError as erro:
                return self._json(HTTPStatus.BAD_REQUEST, {"erro": str(erro)})

        if url.path == "/api/saude":
            return self._json(HTTPStatus.OK, {"estado": "ok"})

        self._json(HTTPStatus.NOT_FOUND, {"erro": "não encontrado"})

    def do_POST(self):
        if urlparse(self.path).path != "/api/eventos":
            return self._json(HTTPStatus.NOT_FOUND, {"erro": "não encontrado"})
        try:
            tamanho = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            tamanho = -1
        if tamanho <= 0 or tamanho > MAX_CORPO:
            return self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE if tamanho > MAX_CORPO
                              else HTTPStatus.BAD_REQUEST, {"erro": "corpo inválido"})
        try:
            # navigator.sendBeacon envia text/plain: aceitamos JSON em qualquer Content-Type.
            corpo = json.loads(self.rfile.read(tamanho).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._json(HTTPStatus.BAD_REQUEST, {"erro": "JSON inválido"})
        eventos = corpo.get("eventos") if isinstance(corpo, dict) else corpo
        if isinstance(eventos, dict):
            eventos = [eventos]
        if not isinstance(eventos, list):
            return self._json(HTTPStatus.BAD_REQUEST, {"erro": "esperava 'eventos': [...]"})
        conn = analytics.ligar(Config.bd)
        try:
            aceites = analytics.inserir_eventos(conn, eventos[:MAX_EVENTOS_POR_PEDIDO])
        finally:
            conn.close()
        self._json(HTTPStatus.OK, {"aceites": aceites, "rejeitados": len(eventos) - aceites})


def main():
    ap = argparse.ArgumentParser(description="Servidor de métricas da Biblioteca Virtual")
    ap.add_argument("--host", default=os.environ.get("BIBLIO_HOST", "127.0.0.1"))
    ap.add_argument("--porta", type=int, default=int(os.environ.get("BIBLIO_PORTA", "8080")))
    ap.add_argument("--bd", default=Config.bd, help="ficheiro SQLite")
    args = ap.parse_args()
    Config.bd = args.bd
    analytics.ligar(Config.bd).close()  # cria o esquema logo no arranque
    srv = ThreadingHTTPServer((args.host, args.porta), Handler)
    print(f"Painel:      http://{args.host}:{args.porta}/")
    print(f"Demo:        http://{args.host}:{args.porta}/demo")
    print(f"Recolha:     POST http://{args.host}:{args.porta}/api/eventos")
    print(f"Base dados:  {Path(Config.bd).resolve()}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nA terminar…")


if __name__ == "__main__":
    main()
