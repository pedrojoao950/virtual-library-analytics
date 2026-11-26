/*
 * Biblioteca Analytics — rastreador para a Biblioteca Virtual.
 *
 * Inclua em todas as páginas da biblioteca:
 *   <script src="https://SERVIDOR/tracker.js" defer></script>
 * (opcional) data-endpoint="https://SERVIDOR/api/eventos"
 *
 * Depois chame, nos pontos certos do seu código:
 *   BibliotecaAnalytics.inicioPesquisa()                 // opcional: utilizador começou a escrever
 *   BibliotecaAnalytics.pesquisa(termo, numResultados)    // pesquisa submetida
 *   BibliotecaAnalytics.cliqueResultado(id, titulo, pos)  // clicou num resultado
 *   BibliotecaAnalytics.vistaLivro(id, titulo)            // abriu a ficha do livro
 *   BibliotecaAnalytics.iniciarLeitura(id, titulo)        // abriu o leitor
 *   BibliotecaAnalytics.terminarLeitura()                 // fechou o leitor
 *   BibliotecaAnalytics.naoEncontrado(termoOuTitulo)      // pedido de livro inexistente
 *
 * Sem configuração extra também pode usar atributos HTML:
 *   <input data-ba-pesquisa>  → mede automaticamente o tempo a escrever a pesquisa
 *
 * Computadores da biblioteca: para identificar cada computador, abra uma vez nesse
 * computador qualquer página da biblioteca com ?ba_posto=NOME (ex.: ?ba_posto=PC-01).
 * O nome fica guardado no navegador. Alternativas: data-posto="PC-01" na tag <script>,
 * BibliotecaAnalytics.definirPosto("PC-01"), ou o ficheiro postos.json no servidor (por IP).
 * Cada computador envia um sinal de presença por minuto, para o painel saber quais
 * estão ativos e quanto tempo foram usados.
 *
 * Privacidade: não recolhe IP, nome, e-mail nem cookies; usa um identificador
 * anónimo aleatório guardado no navegador.
 */
(function () {
  "use strict";
  if (window.BibliotecaAnalytics) return;

  var script = document.currentScript;
  var endpoint = (script && script.getAttribute("data-endpoint")) ||
    (script && script.src ? new URL("/api/eventos", script.src).href : "/api/eventos");

  var SESSAO_INATIVA_MS = 30 * 60 * 1000;
  var LEITURA_TICK_MS = 15 * 1000;       // amostragem do tempo de leitura
  var LEITURA_INATIVO_MS = 2 * 60 * 1000; // sem interação há 2 min = não está a ler
  var LEITURA_ENVIO_MS = 60 * 1000;
  var PRESENCA_MS = 60 * 1000;
  var USO_INATIVO_MS = 5 * 60 * 1000;    // sem interação há 5 min = computador parado

  function uid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return Date.now().toString(36) + Math.random().toString(36).slice(2);
  }
  function guardar(area, k, v) { try { window[area].setItem(k, v); } catch (e) { /* modo privado */ } }
  function ler(area, k) { try { return window[area].getItem(k); } catch (e) { return null; } }

  var utilizador = ler("localStorage", "ba_utilizador") || uid();
  guardar("localStorage", "ba_utilizador", utilizador);

  // ---------------------------------------------------------- computador (posto)
  var posto = null;
  try {
    var doUrl = new URLSearchParams(location.search).get("ba_posto");
    if (doUrl !== null) {
      doUrl = doUrl.trim().slice(0, 80);
      if (doUrl) guardar("localStorage", "ba_posto", doUrl);
      else { try { localStorage.removeItem("ba_posto"); } catch (e) { /* ignora */ } }
    }
  } catch (e) { /* navegador antigo */ }
  posto = (script && script.getAttribute("data-posto")) || window.BA_POSTO || ler("localStorage", "ba_posto") || null;

  function sessao(soLer) {
    var agora = Date.now();
    var id = ler("localStorage", "ba_sessao");
    var ultimo = +ler("localStorage", "ba_sessao_ultimo") || 0;
    if (soLer && id) return id; // sinais de presença não prolongam a sessão
    if (!id || agora - ultimo > SESSAO_INATIVA_MS) id = uid();
    guardar("localStorage", "ba_sessao", id);
    guardar("localStorage", "ba_sessao_ultimo", String(agora));
    return id;
  }

  // ------------------------------------------------------------ fila de envio
  var fila = [];
  function registar(tipo, dados) {
    var ev = { tipo: tipo, ts: Date.now(), sessao: sessao(tipo === "presenca"), utilizador: utilizador, pagina: location.pathname };
    if (posto) ev.posto = posto;
    for (var k in dados) if (dados[k] !== undefined && dados[k] !== null) ev[k] = dados[k];
    fila.push(ev);
    if (fila.length > 300) fila.shift();
    if (fila.length >= 20) enviar();
  }
  function enviar(usarBeacon) {
    if (!fila.length) return;
    var lote = fila.splice(0, fila.length);
    var corpo = JSON.stringify({ eventos: lote });
    if (usarBeacon && navigator.sendBeacon) {
      if (navigator.sendBeacon(endpoint, new Blob([corpo], { type: "text/plain" }))) return;
    }
    fetch(endpoint, { method: "POST", body: corpo, keepalive: true, headers: { "Content-Type": "text/plain" } })
      .then(function (r) { if (!r.ok && r.status >= 500) throw new Error(r.status); })
      .catch(function () { fila = lote.concat(fila).slice(-300); }); // volta a tentar mais tarde
  }
  setInterval(enviar, 5000);

  // ---------------------------------------------------------------- pesquisa
  var inicioEscrita = null;
  var ultimaPesquisa = null; // { id, termo, ts }

  function inicioPesquisa() { if (inicioEscrita === null) inicioEscrita = Date.now(); }

  function pesquisa(termo, numResultados) {
    termo = String(termo || "").trim();
    if (!termo) return null;
    var agora = Date.now();
    var id = uid();
    registar("pesquisa", {
      termo: termo, num_resultados: Math.max(0, numResultados | 0), pesquisa_id: id,
      duracao_ms: inicioEscrita !== null ? agora - inicioEscrita : undefined
    });
    inicioEscrita = null;
    ultimaPesquisa = { id: id, termo: termo, ts: agora };
    guardar("sessionStorage", "ba_ultima_pesquisa", JSON.stringify(ultimaPesquisa));
    return id;
  }

  function cliqueResultado(livroId, titulo, posicao) {
    var p = ultimaPesquisa;
    if (!p) { try { p = JSON.parse(ler("sessionStorage", "ba_ultima_pesquisa")); } catch (e) { p = null; } }
    registar("clique_resultado", {
      livro_id: String(livroId), livro_titulo: titulo, posicao: posicao,
      pesquisa_id: p ? p.id : undefined, termo: p ? p.termo : undefined,
      duracao_ms: p ? Date.now() - p.ts : undefined
    });
    enviar(true);
  }

  document.addEventListener("input", function (e) {
    if (e.target && e.target.closest && e.target.closest("[data-ba-pesquisa]")) inicioPesquisa();
  }, true);

  // ----------------------------------------------------------------- leitura
  var leitura = null; // { id, titulo, acumulado, ultimoTick, ultimoEnvio }
  var ultimaInteracao = Date.now();
  ["scroll", "keydown", "pointerdown", "pointermove", "touchstart", "wheel"].forEach(function (n) {
    window.addEventListener(n, function () { ultimaInteracao = Date.now(); }, { passive: true, capture: true });
  });

  function tick() {
    if (!leitura) return;
    var agora = Date.now();
    var ativo = document.visibilityState === "visible" && agora - ultimaInteracao < LEITURA_INATIVO_MS;
    if (ativo) leitura.acumulado += Math.min(agora - leitura.ultimoTick, LEITURA_TICK_MS * 2);
    leitura.ultimoTick = agora;
    if (agora - leitura.ultimoEnvio >= LEITURA_ENVIO_MS) descarregarLeitura();
  }
  function descarregarLeitura() {
    if (!leitura) return;
    if (leitura.acumulado >= 1000) {
      registar("leitura", { livro_id: leitura.id, livro_titulo: leitura.titulo, duracao_ms: Math.round(leitura.acumulado) });
    }
    leitura.acumulado = 0;
    leitura.ultimoEnvio = Date.now();
  }
  setInterval(tick, LEITURA_TICK_MS);

  function iniciarLeitura(livroId, titulo) {
    if (leitura) terminarLeitura();
    var agora = Date.now();
    ultimaInteracao = agora;
    leitura = { id: String(livroId), titulo: titulo, acumulado: 0, ultimoTick: agora, ultimoEnvio: agora };
  }
  function terminarLeitura() {
    if (!leitura) return;
    tick();
    descarregarLeitura();
    leitura = null;
    enviar(true);
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") { tick(); descarregarLeitura(); enviar(true); }
    else if (leitura) { leitura.ultimoTick = Date.now(); ultimaInteracao = Date.now(); }
  });
  window.addEventListener("pagehide", function () { tick(); descarregarLeitura(); enviar(true); });

  // ---------------------------------------------------------------- presença
  var ultimoSinal = Date.now();
  function presenca() {
    var agora = Date.now();
    var emUso = document.visibilityState === "visible" && agora - ultimaInteracao < USO_INATIVO_MS;
    registar("presenca", { duracao_ms: emUso ? Math.min(agora - ultimoSinal, PRESENCA_MS * 2) : 0 });
    ultimoSinal = agora;
    enviar();
  }
  setInterval(presenca, PRESENCA_MS);

  // ------------------------------------------------------------------ resto
  window.BibliotecaAnalytics = {
    inicioPesquisa: inicioPesquisa,
    pesquisa: pesquisa,
    cliqueResultado: cliqueResultado,
    vistaLivro: function (id, titulo) { registar("vista_livro", { livro_id: String(id), livro_titulo: titulo }); },
    iniciarLeitura: iniciarLeitura,
    terminarLeitura: terminarLeitura,
    naoEncontrado: function (termoOuTitulo) { registar("nao_encontrado", { termo: String(termoOuTitulo || "") }); enviar(); },
    enviarAgora: function () { enviar(); },
    definirPosto: function (nome) {
      posto = String(nome || "").trim().slice(0, 80) || null;
      if (posto) guardar("localStorage", "ba_posto", posto);
      else { try { localStorage.removeItem("ba_posto"); } catch (e) { /* ignora */ } }
    },
    posto: function () { return posto; }
  };

  registar("vista_pagina", {});
  registar("presenca", { duracao_ms: 0 });
})();
