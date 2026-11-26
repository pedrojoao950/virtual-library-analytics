import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from datetime import date, datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analytics  # noqa: E402

FUSO = timezone(timedelta(hours=1))
HOJE = date(2026, 11, 26)  # quinta-feira


def ms(dia, hora=10, minuto=0):
    return int(datetime(dia.year, dia.month, dia.day, hora, minuto, tzinfo=FUSO).timestamp() * 1000)


class TestMetricas(unittest.TestCase):
    def setUp(self):
        self.conn = analytics.ligar(":memory:")
        d0, d1 = HOJE, HOJE - timedelta(days=1)
        ev = [
            # sessão A (ontem): pesquisa com sucesso + leitura de 3 min
            {"tipo": "vista_pagina", "ts": ms(d1), "sessao": "A", "utilizador": "u1"},
            {"tipo": "pesquisa", "ts": ms(d1, 10, 1), "sessao": "A", "utilizador": "u1", "termo": "Pepetela",
             "num_resultados": 2, "pesquisa_id": "p1", "duracao_ms": 4000},
            {"tipo": "clique_resultado", "ts": ms(d1, 10, 2), "sessao": "A", "utilizador": "u1", "pesquisa_id": "p1",
             "livro_id": "mayombe", "livro_titulo": "Mayombe", "posicao": 1, "duracao_ms": 6000},
            {"tipo": "vista_livro", "ts": ms(d1, 10, 2), "sessao": "A", "utilizador": "u1", "livro_id": "mayombe",
             "livro_titulo": "Mayombe"},
            {"tipo": "leitura", "ts": ms(d1, 10, 3), "sessao": "A", "utilizador": "u1", "livro_id": "mayombe",
             "livro_titulo": "Mayombe", "duracao_ms": 120000},
            {"tipo": "leitura", "ts": ms(d1, 10, 4), "sessao": "A", "utilizador": "u1", "livro_id": "mayombe",
             "livro_titulo": "Mayombe", "duracao_ms": 60000},
            # sessão B (hoje): pesquisa sem resultados + pedido + pesquisa sem clique
            {"tipo": "pesquisa", "ts": ms(d0), "sessao": "B", "utilizador": "u2", "termo": "Harry Potter",
             "num_resultados": 0, "pesquisa_id": "p2", "duracao_ms": 3000},
            {"tipo": "nao_encontrado", "ts": ms(d0, 10, 1), "sessao": "B", "utilizador": "u2", "termo": "harry  potter"},
            {"tipo": "pesquisa", "ts": ms(d0, 10, 2), "sessao": "B", "utilizador": "u2", "termo": "pépetela ",
             "num_resultados": 2, "pesquisa_id": "p3", "duracao_ms": 2000},
            # leitura de 1 min de outro livro hoje
            {"tipo": "leitura", "ts": ms(d0, 23, 30), "sessao": "B", "utilizador": "u2", "livro_id": "luuanda",
             "livro_titulo": "Luuanda", "duracao_ms": 60000},
        ]
        self.assertEqual(analytics.inserir_eventos(self.conn, ev, agora_ms=ms(HOJE, 12)), len(ev))

    def tearDown(self):
        self.conn.close()

    def m(self, **kw):
        kw.setdefault("periodo", "7d")
        return analytics.metricas(self.conn, hoje=HOJE, fuso_horas=1, **kw)

    def test_resumo(self):
        r = self.m()["resumo"]
        self.assertEqual(r["sessoes"], 2)
        self.assertEqual(r["utilizadores"], 2)
        self.assertEqual(r["pesquisas"], 3)
        self.assertEqual(r["taxa_sucesso_pesquisa"], 33.3)
        self.assertEqual(r["taxa_sem_resultados"], 33.3)
        self.assertEqual(r["taxa_abandono_pesquisa"], 33.3)
        self.assertEqual(r["tempo_medio_ate_encontrar_s"], 6.0)
        self.assertEqual(r["tempo_medio_pesquisa_total_s"], 10.0)
        self.assertEqual(r["tempo_medio_escrita_pesquisa_s"], 3.0)
        self.assertEqual(r["tempo_leitura_total_min"], 4.0)
        self.assertEqual(r["leitores"], 2)
        self.assertEqual(r["pedidos_nao_encontrados"], 1)

    def test_rankings(self):
        d = self.m()
        self.assertEqual(d["mais_lidos"][0]["livro_id"], "mayombe")
        self.assertEqual(d["mais_lidos"][0]["minutos"], 3.0)
        termos = {t["termo"].strip().lower(): t for t in d["mais_procurados_termos"]}
        # "Pepetela" e "pépetela " são o mesmo termo normalizado
        self.assertEqual(d["mais_procurados_termos"][0]["pesquisas"], 2)
        self.assertEqual(len(termos), 2)
        nao = d["nao_encontrados"][0]
        self.assertEqual(nao["vezes"], 2)
        self.assertEqual(nao["pedidos_explicitos"], 1)
        self.assertEqual(d["mais_procurados_livros"][0]["vistas"], 1)

    def test_periodo_hoje_e_series(self):
        d = self.m(periodo="hoje")
        self.assertEqual(d["resumo"]["pesquisas"], 2)
        self.assertEqual(d["resumo"]["tempo_leitura_total_min"], 1.0)  # 23:30 local ainda é hoje
        s = self.m(agrupar="dia")["serie"]
        self.assertEqual(len(s), 7)
        self.assertEqual(s[-2]["minutos_leitura"], 3.0)
        self.assertEqual(s[-1]["sem_resultados"], 1)
        semana = self.m(agrupar="semana")["serie"]
        self.assertEqual(semana[-1]["periodo"], "2026-11-23")  # segunda-feira
        self.assertEqual(sum(x["pesquisas"] for x in semana), 3)
        mes = self.m(periodo="12m", agrupar="mes")["serie"]
        self.assertEqual(mes[-1]["periodo"], "2026-11")
        self.assertEqual(mes[-1]["minutos_leitura"], 4.0)
        self.assertEqual(len(mes), 13)

    def test_validacao(self):
        maus = [{"tipo": "xpto", "sessao": "x"}, {"tipo": "pesquisa", "sessao": "x"},
                {"tipo": "leitura", "sessao": "x", "livro_id": "a"}, "lixo", {"tipo": "vista_pagina"}]
        self.assertEqual(analytics.inserir_eventos(self.conn, maus), 0)
        e = analytics.validar_evento({"tipo": "leitura", "sessao": "x", "livro_id": "a", "duracao_ms": 10 ** 9,
                                      "ts": 0}, agora_ms=10 ** 12)
        self.assertEqual(e["duracao_ms"], analytics.MAX_LEITURA_BLOCO_MS)
        self.assertEqual(e["ts"], 10 ** 12)  # relógio do cliente absurdo → hora de receção

    def test_csv(self):
        txt = analytics.para_csv(self.m(), "mais_lidos")
        self.assertTrue(txt.startswith("livro_id;titulo;minutos"))
        self.assertIn("Mayombe", txt)


class TestServidor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["BIBLIO_SILENCIOSO"] = "1"
        import servidor
        cls.tmp = tempfile.TemporaryDirectory()
        servidor.Config.bd = os.path.join(cls.tmp.name, "t.db")
        servidor.Config.token = None
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), servidor.Handler)
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def test_fluxo(self):
        corpo = json.dumps({"eventos": [
            {"tipo": "pesquisa", "sessao": "s", "termo": "ondjaki", "num_resultados": 0},
            {"tipo": "invalido", "sessao": "s"},
        ]}).encode()
        req = urllib.request.Request(self.url + "/api/eventos", data=corpo, headers={"Content-Type": "text/plain"})
        with urllib.request.urlopen(req) as r:
            self.assertEqual(json.load(r), {"aceites": 1, "rejeitados": 1})
        with urllib.request.urlopen(self.url + "/api/metricas?periodo=hoje") as r:
            d = json.load(r)
        self.assertEqual(d["resumo"]["pesquisas"], 1)
        self.assertEqual(d["nao_encontrados"][0]["termo"], "ondjaki")
        with urllib.request.urlopen(self.url + "/api/exportar?periodo=hoje&tabela=nao_encontrados") as r:
            self.assertIn("text/csv", r.headers["Content-Type"])
            self.assertIn("ondjaki", r.read().decode("utf-8-sig"))
        for p in ("/", "/tracker.js", "/demo"):
            with urllib.request.urlopen(self.url + p) as r:
                self.assertEqual(r.status, 200)


if __name__ == "__main__":
    unittest.main()
