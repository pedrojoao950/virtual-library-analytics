import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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

    def test_computadores(self):
        agora = ms(HOJE, 12)
        ev = [{"tipo": "presenca", "ts": agora - 60000, "sessao": "C", "posto": "PC-01", "duracao_ms": 60000},
              {"tipo": "presenca", "ts": agora - 30 * 60000, "sessao": "D", "posto": "PC-02", "duracao_ms": 120000},
              {"tipo": "pesquisa", "ts": agora - 60000, "sessao": "C", "termo": "x", "num_resultados": 0,
               "posto": "PC-01"}]
        self.assertEqual(analytics.inserir_eventos(self.conn, ev, agora_ms=agora), 3)
        d = self.m(periodo="hoje", agora_ms=agora)
        pcs = {c["posto"]: c for c in d["computadores"]}
        self.assertTrue(pcs["PC-01"]["ativo_agora"])
        self.assertFalse(pcs["PC-02"]["ativo_agora"])
        self.assertEqual(pcs["PC-02"]["minutos_sem_atividade"], 30)
        self.assertEqual(pcs["PC-01"]["pesquisas"], 1)
        self.assertEqual(pcs["PC-01"]["sessoes"], 1)  # presença não conta como sessão
        self.assertEqual(pcs["PC-02"]["sessoes"], 0)
        self.assertIn(None, pcs)  # acessos sem computador identificado
        # presença não altera as métricas de navegação
        self.assertEqual(d["resumo"]["sessoes"], 2)
        # filtro por computador
        f = self.m(periodo="hoje", posto="PC-01", agora_ms=agora)
        self.assertEqual(f["resumo"]["pesquisas"], 1)
        self.assertEqual([c["posto"] for c in f["computadores"]], ["PC-01"])
        sem = self.m(periodo="hoje", posto=analytics.SEM_POSTO, agora_ms=agora)
        self.assertEqual(sem["resumo"]["pesquisas"], 2)
        # posto atribuído pelo servidor (p. ex. por IP) quando o evento não traz um
        analytics.inserir_eventos(self.conn, [{"tipo": "vista_pagina", "sessao": "E", "ts": agora}],
                                  agora_ms=agora, posto_omissao="PC-03")
        self.assertEqual(analytics.lista_postos(self.conn), ["PC-01", "PC-02", "PC-03"])

    def test_migracao(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = os.path.join(tmp, "antiga.db")
            import sqlite3
            c = sqlite3.connect(caminho)
            c.executescript(analytics.ESQUEMA.replace(",\n    posto          TEXT", ""))
            c.close()
            conn = analytics.ligar(caminho)
            self.assertEqual(analytics.inserir_eventos(conn, [{"tipo": "vista_pagina", "sessao": "x", "posto": "PC"}]), 1)
            conn.close()

    def test_csv(self):
        txt = analytics.para_csv(self.m(), "mais_lidos")
        self.assertTrue(txt.startswith("livro_id;titulo;minutos"))
        self.assertIn("Mayombe", txt)


CABECALHO_COUNTER = [
    ["Report_Name", "Book Requests (Controlled)"], ["Report_ID", "TR_B1"], ["Release", "5.1"],
    ["Institution_Name", "Universidade X"], ["Metric_Types", "Total_Item_Requests; Unique_Title_Requests"],
    ["Reporting_Period", "Begin_Date=2026-09-01; End_Date=2026-10-31"], [],
    ["Title", "Publisher", "Publisher_ID", "Platform", "DOI", "Proprietary_ID", "ISBN", "Print_ISSN", "Online_ISSN",
     "URI", "YOP", "Metric_Type", "Reporting_Period_Total", "Sep-2026", "Oct-2026"],
    ["Mayombe", "Ed. A", "", "Perlego", "", "123", "978-1", "", "", "", "1980", "Total_Item_Requests", "30", "10", "20"],
    ["Mayombe", "Ed. A", "", "Perlego", "", "123", "978-1", "", "", "", "1980", "Unique_Title_Requests", "12", "5", "7"],
    ["Luuanda", "Ed. B", "", "Perlego", "", "456", "978-2", "", "", "", "1963", "Unique_Title_Requests", "4", "", "4"],
]


def _xlsx(linhas):
    import io
    import zipfile
    from xml.sax.saxutils import escape
    folha = "".join(
        "<row>" + "".join(f'<c r="{chr(65 + j)}{i + 1}" t="inlineStr"><is><t>{escape(v)}</t></is></c>'
                          for j, v in enumerate(linha) if v) + "</row>"
        for i, linha in enumerate(linhas))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/worksheets/sheet1.xml",
                   '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   f"<sheetData>{folha}</sheetData></worksheet>")
    return buf.getvalue()


class TestCounter(unittest.TestCase):
    def setUp(self):
        self.conn = analytics.ligar(":memory:")

    def tearDown(self):
        self.conn.close()

    def _verificar(self, conteudo):
        r = analytics.importar_counter(self.conn, conteudo)
        self.assertEqual(r["relatorio"], "TR_B1")
        self.assertEqual(r["titulos"], 2)
        self.assertEqual(r["meses"], ["2026-09", "2026-10"])
        c = analytics.metricas_counter(self.conn, date(2026, 9, 1), date(2026, 10, 31))
        self.assertTrue(c["disponivel"])
        self.assertEqual(c["mais_lidos"][0]["titulo"], "Mayombe")
        self.assertEqual(c["mais_lidos"][0]["unicos"], 12)
        self.assertEqual(c["mais_lidos"][0]["total"], 30)
        self.assertEqual([m["unicos"] for m in c["por_mes"]], [5, 11])
        # só outubro
        c = analytics.metricas_counter(self.conn, date(2026, 10, 5), date(2026, 10, 20))
        self.assertEqual(c["total_unicos"], 11)

    def test_csv_tsv_xlsx(self):
        import csv
        import io
        for sep in (",", "\t", ";"):
            buf = io.StringIO()
            csv.writer(buf, delimiter=sep).writerows(CABECALHO_COUNTER)
            self._verificar(buf.getvalue().encode("utf-8"))
        self._verificar(_xlsx(CABECALHO_COUNTER))
        # reimportar não duplica
        analytics.importar_counter(self.conn, _xlsx(CABECALHO_COUNTER))
        c = analytics.metricas_counter(self.conn, date(2026, 9, 1), date(2026, 10, 31))
        self.assertEqual(c["total_unicos"], 16)

    def test_invalido(self):
        with self.assertRaises(ValueError):
            analytics.importar_counter(self.conn, b"a,b,c\n1,2,3\n")
        self.assertFalse(analytics.metricas_counter(self.conn, date(2026, 1, 1), date(2026, 2, 1))["disponivel"])


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
        req = urllib.request.Request(self.url + "/api/eventos", data=json.dumps(
            [{"tipo": "presenca", "sessao": "s2", "posto": "PC-07", "duracao_ms": 60000}]).encode())
        urllib.request.urlopen(req).close()
        with urllib.request.urlopen(self.url + "/api/postos") as r:
            self.assertEqual(json.load(r)["postos"], ["PC-07"])
        with urllib.request.urlopen(self.url + "/api/metricas?periodo=hoje&posto=PC-07") as r:
            d = json.load(r)
        self.assertTrue(d["computadores"][0]["ativo_agora"])
        self.assertEqual(d["resumo"]["pesquisas"], 0)
        req = urllib.request.Request(self.url + "/api/importar-counter", data=_xlsx(CABECALHO_COUNTER))
        with urllib.request.urlopen(req) as r:
            self.assertEqual(json.load(r)["titulos"], 2)
        with self.assertRaises(urllib.error.HTTPError) as erro:
            urllib.request.urlopen(urllib.request.Request(self.url + "/api/importar-counter", data=b"lixo"))
        self.assertEqual(erro.exception.code, 400)
        for p in ("/", "/tracker.js", "/demo"):
            with urllib.request.urlopen(self.url + p) as r:
                self.assertEqual(r.status, 200)


class TestServidorProducao(unittest.TestCase):
    """Configuração de produção: chave de recolha, token do painel e /demo desligada."""

    @classmethod
    def setUpClass(cls):
        os.environ["BIBLIO_SILENCIOSO"] = "1"
        import servidor
        cls.servidor = servidor
        cls.antes = (servidor.Config.bd, servidor.Config.token, servidor.Config.chave_recolha, servidor.Config.demo)
        cls.tmp = tempfile.TemporaryDirectory()
        servidor.Config.bd = os.path.join(cls.tmp.name, "p.db")
        servidor.Config.token, servidor.Config.chave_recolha, servidor.Config.demo = "tok", "chave-secreta", False
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), servidor.Handler)
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        c = cls.servidor.Config
        c.bd, c.token, c.chave_recolha, c.demo = cls.antes
        cls.tmp.cleanup()

    def _post(self, corpo, sufixo=""):
        req = urllib.request.Request(self.url + "/api/eventos" + sufixo, data=json.dumps(corpo).encode())
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def _get(self, caminho):
        try:
            with urllib.request.urlopen(self.url + caminho) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_chave(self):
        ev = [{"tipo": "vista_pagina", "sessao": "s"}]
        self.assertEqual(self._post({"eventos": ev})[0], 401)
        self.assertEqual(self._post({"eventos": ev, "chave": "errada"})[0], 401)
        self.assertEqual(self._post({"eventos": ev, "chave": "chave-secreta"}), (200, {"aceites": 1, "rejeitados": 0}))
        self.assertEqual(self._post({"eventos": ev}, "?chave=chave-secreta")[0], 200)

    def test_painel_e_demo(self):
        self.assertEqual(self._get("/"), 401)
        self.assertEqual(self._get("/?token=tok"), 200)
        self.assertEqual(self._get("/api/metricas?periodo=hoje"), 401)
        self.assertEqual(self._get("/api/metricas?periodo=hoje&token=tok"), 200)
        self.assertEqual(self._get("/demo"), 404)
        self.assertEqual(self._get("/tracker.js"), 200)
        self.assertEqual(self._get("/api/saude"), 200)


class TestRelatorioMensal(unittest.TestCase):
    def setUp(self):
        try:
            import reportlab  # noqa: F401
        except ImportError:
            self.skipTest("reportlab não instalado")
        import relatorio_mensal
        self.rm = relatorio_mensal
        self.conn = analytics.ligar(":memory:")
        agora = ms(date(2026, 10, 15), 10)
        analytics.inserir_eventos(self.conn, [
            {"tipo": "pesquisa", "ts": agora, "sessao": "a", "termo": "Harry Potter", "num_resultados": 0, "posto": "PC-01"},
            {"tipo": "leitura", "ts": agora, "sessao": "a", "livro_id": "1", "livro_titulo": "Mayombe",
             "duracao_ms": 120000, "posto": "PC-01"},
        ], agora_ms=agora)

    def tearDown(self):
        self.conn.close()

    def test_intervalos(self):
        ini, fim, t = self.rm.intervalo_mes("2026-02", 1)
        self.assertEqual((ini, fim, t), (date(2026, 2, 1), date(2026, 2, 28), "fevereiro de 2026"))

    def test_pdf_e_envio_brevo(self):
        dados, anterior = self.rm.recolher(self.conn, date(2026, 10, 1), date(2026, 10, 31), 1)
        self.assertEqual(dados["resumo"]["pesquisas"], 1)
        pdf = self.rm.gerar_pdf(dados, anterior, "outubro de 2026", "Instituição X")
        self.assertTrue(pdf.startswith(b"%PDF"))
        obs = self.rm.observacoes(dados["resumo"], anterior["resumo"], dados)
        self.assertTrue(any("Harry Potter" in o for o in obs))

        recebido = {}

        class Brevo(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                recebido["chave"] = self.headers.get("api-key")
                recebido["corpo"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                self.send_response(201)
                self.end_headers()
                self.wfile.write(b"{}")

        srv = ThreadingHTTPServer(("127.0.0.1", 0), Brevo)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.rm.BREVO_URL = f"http://127.0.0.1:{srv.server_address[1]}/v3/smtp/email"
        env = {"BIBLIO_EMAIL_PARA": "a@x.ao, b@x.ao", "BIBLIO_EMAIL_DE": "biblioteca@x.ao", "BIBLIO_BREVO_CHAVE": "k1"}
        antigo = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            txt = self.rm.enviar("Assunto", "<p>oi</p>", pdf, "r.pdf")
        finally:
            for k, v in antigo.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            srv.shutdown()
            srv.server_close()
        self.assertIn("Brevo", txt)
        self.assertEqual(recebido["chave"], "k1")
        self.assertEqual([t["email"] for t in recebido["corpo"]["to"]], ["a@x.ao", "b@x.ao"])
        import base64
        self.assertTrue(base64.b64decode(recebido["corpo"]["attachment"][0]["content"]).startswith(b"%PDF"))

    def test_sem_configuracao(self):
        with self.assertRaises(RuntimeError):
            self.rm.enviar("A", "b", b"%PDF", "r.pdf")


if __name__ == "__main__":
    unittest.main()
