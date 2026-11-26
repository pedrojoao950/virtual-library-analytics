// Corre dentro das páginas da Perlego. Lê apenas o endereço da página, o termo pesquisado,
// os links para livros e o título do livro. Não lê nomes, e-mails nem dados da conta.
(async () => {
  "use strict";
  const { cfg } = await lerConfig();
  const reLivro = new RegExp(cfg.regexLivro, "i");
  const reLeitor = new RegExp(cfg.regexLeitor, "i");
  const rePesquisa = new RegExp(cfg.regexPesquisa, "i");

  const LEITURA_TICK_MS = 15000, LEITURA_INATIVO_MS = 2 * 60000, LEITURA_ENVIO_MS = 60000;

  function registar(tipo, dados = {}) {
    const ev = { tipo, ts: Date.now(), pagina: location.pathname.replace(/\d{3,}/g, "N"), ...dados };
    try { chrome.runtime.sendMessage({ ba_evento: ev }); } catch (e) { /* extensão recarregada */ }
    diag(`${tipo}${dados.termo ? ` “${dados.termo}”` : ""}${dados.num_resultados !== undefined ? ` → ${dados.num_resultados} resultados` : ""}` +
         `${dados.livro_titulo ? ` · ${dados.livro_titulo}` : dados.livro_id ? ` · livro ${dados.livro_id}` : ""}` +
         `${dados.duracao_ms ? ` · ${Math.round(dados.duracao_ms / 1000)} s` : ""}`);
  }

  // ---------------------------------------------------------------- diagnóstico
  let caixa = null;
  function diag(texto) {
    if (!cfg.diagnostico) return;
    if (!caixa) {
      caixa = document.createElement("div");
      caixa.style.cssText = "position:fixed;right:12px;bottom:12px;z-index:2147483647;max-width:360px;" +
        "font:12px/1.4 system-ui,sans-serif;background:#191919;color:#efefef;padding:8px 10px;border-radius:8px;" +
        "box-shadow:0 4px 16px rgba(0,0,0,.3);pointer-events:none;white-space:pre-line";
      document.documentElement.append(caixa);
    }
    const linhas = (caixa.textContent ? caixa.textContent.split("\n") : []).slice(-5);
    linhas.push(new Date().toLocaleTimeString() + "  " + texto);
    caixa.textContent = "Biblioteca Analytics (diagnóstico)\n" + linhas.filter((l) => !l.startsWith("Biblioteca")).join("\n");
  }

  // ----------------------------------------------------------------- utilitários
  const idLivro = (href) => { try { const m = new URL(href, location.href).pathname.match(reLivro); return m ? m[1] : null; } catch (e) { return null; } };
  function tituloPagina() {
    const h1 = document.querySelector("h1");
    const t = (h1 && h1.textContent.trim()) || document.title.split(/\s+[|–-]\s+Perlego/i)[0].trim();
    return t.slice(0, 300) || undefined;
  }
  function termoDoUrl() {
    const p = new URLSearchParams(location.search);
    for (const k of ["query", "q", "search", "term", "keyword", "keywords"]) if (p.get(k)) return p.get(k).trim();
    return "";
  }
  // Links para livros visíveis na página, sem repetidos, pela ordem em que aparecem.
  function livrosNaPagina() {
    const vistos = new Map();
    for (const a of document.querySelectorAll("a[href]")) {
      const id = idLivro(a.getAttribute("href"));
      if (id && !vistos.has(id) && a.offsetParent !== null && !a.closest("header, nav, footer")) vistos.set(id, a);
    }
    return [...vistos.keys()];
  }
  const semResultadosNoTexto = () => /\b(no results|0 results|nothing found|sem resultados|nenhum resultado|we couldn.t find)\b/i
    .test((document.querySelector("main") || document.body).innerText.slice(0, 20000));

  // ------------------------------------------------------------------- pesquisa
  let inicioEscrita = null;
  let ultimaPesquisa = null; // { termo, ts, livros: [...] }
  document.addEventListener("input", (e) => {
    const t = e.target;
    if (t && t.matches && t.matches("input[type=search], input[type=text], input:not([type])") && inicioEscrita === null) inicioEscrita = Date.now();
  }, true);

  async function contarResultados() {
    // espera que a lista estabilize (a Perlego carrega resultados dinamicamente)
    let anterior = -1, estavelDesde = Date.now();
    const limite = Date.now() + 10000;
    while (Date.now() < limite) {
      await new Promise((r) => setTimeout(r, 500));
      const n = livrosNaPagina().length;
      if (ultimaPesquisa) ultimaPesquisa.livrosVistos = livrosNaPagina();
      if (n !== anterior) { anterior = n; estavelDesde = Date.now(); }
      if ((n > 0 && Date.now() - estavelDesde > 1500) || (n === 0 && semResultadosNoTexto() && Date.now() - estavelDesde > 1500)) break;
    }
    return livrosNaPagina();
  }

  async function novaPesquisa(termo) {
    if (!termo || (ultimaPesquisa && ultimaPesquisa.termo === termo && Date.now() - ultimaPesquisa.ts < 3000)) return;
    const submetida = Date.now();
    // ignora tempos de escrita absurdos (ex.: o utilizador escreveu noutro campo há muito tempo)
    const escrita = inicioEscrita !== null && submetida - inicioEscrita < 5 * 60000 ? submetida - inicioEscrita : undefined;
    inicioEscrita = null;
    const atual = { termo, ts: submetida, id: crypto.randomUUID(), livros: [], escrita, registada: false };
    ultimaPesquisa = atual;
    concluirPesquisa(atual, await contarResultados());
  }
  // Regista a pesquisa uma única vez: quando a lista estabiliza, ou antes, se o utilizador
  // clicar num resultado ou sair da página enquanto ainda estamos a contar.
  function concluirPesquisa(p, livros) {
    if (!p || p.registada) return;
    p.registada = true;
    p.livros = livros;
    registar("pesquisa", { termo: p.termo, num_resultados: livros.length, pesquisa_id: p.id, duracao_ms: p.escrita });
  }

  // clique num livro a partir dos resultados
  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest("a[href]");
    if (!a || !ultimaPesquisa || !rePesquisa.test(location.pathname + location.search)) return;
    const id = idLivro(a.getAttribute("href"));
    if (!id) return;
    concluirPesquisa(ultimaPesquisa, livrosNaPagina());
    const lista = ultimaPesquisa.livros.length ? ultimaPesquisa.livros : livrosNaPagina();
    const pos = lista.indexOf(id) + 1;
    registar("clique_resultado", {
      livro_id: id, livro_titulo: (a.textContent || "").trim().slice(0, 300) || undefined,
      posicao: pos || undefined, pesquisa_id: ultimaPesquisa.id, termo: ultimaPesquisa.termo,
      duracao_ms: Date.now() - ultimaPesquisa.ts,
    });
  }, true);

  // ------------------------------------------------------------------- leitura
  let leitura = null;
  let ultimaInteracao = Date.now();
  for (const n of ["scroll", "keydown", "pointerdown", "pointermove", "touchstart", "wheel"]) {
    addEventListener(n, () => { ultimaInteracao = Date.now(); }, { passive: true, capture: true });
  }
  function tick() {
    if (!leitura) return;
    const agora = Date.now();
    if (document.visibilityState === "visible" && document.hasFocus() && agora - ultimaInteracao < LEITURA_INATIVO_MS) {
      leitura.acumulado += Math.min(agora - leitura.ultimoTick, LEITURA_TICK_MS * 2);
    }
    leitura.ultimoTick = agora;
    if (agora - leitura.ultimoEnvio >= LEITURA_ENVIO_MS) descarregar();
  }
  function descarregar() {
    if (!leitura) return;
    if (leitura.acumulado >= 1000) registar("leitura", { livro_id: leitura.id, livro_titulo: leitura.titulo, duracao_ms: Math.round(leitura.acumulado) });
    leitura.acumulado = 0;
    leitura.ultimoEnvio = Date.now();
  }
  setInterval(tick, LEITURA_TICK_MS);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") { tick(); descarregar(); }
    else if (leitura) { leitura.ultimoTick = Date.now(); }
  });
  addEventListener("pagehide", () => {
    tick(); descarregar();
    if (ultimaPesquisa && !ultimaPesquisa.registada) concluirPesquisa(ultimaPesquisa, livrosNaPagina());
    try { chrome.runtime.sendMessage({ ba_enviar: true }); } catch (e) { /* extensão recarregada */ }
  });

  // -------------------------------------------- mudança de página (a Perlego é uma SPA)
  let urlAnterior = null;
  async function aoMudarPagina() {
    const caminho = location.pathname + location.search;
    tick(); descarregar();
    if (ultimaPesquisa && !ultimaPesquisa.registada) concluirPesquisa(ultimaPesquisa, ultimaPesquisa.livrosVistos || []);
    const idAnterior = leitura && leitura.id;
    leitura = null;
    if (rePesquisa.test(caminho)) {
      novaPesquisa(termoDoUrl());
      return;
    }
    const id = idLivro(location.href);
    if (!id) { diag("página sem livro: " + location.pathname.replace(/\d{3,}/g, "N")); return; }
    await new Promise((r) => setTimeout(r, 1500)); // deixar o título carregar
    if (location.pathname + location.search !== caminho) return;
    const titulo = tituloPagina();
    if (reLeitor.test(caminho)) {
      const agora = Date.now();
      leitura = { id, titulo, acumulado: 0, ultimoTick: agora, ultimoEnvio: agora };
      ultimaInteracao = agora;
      diag(`a ler livro ${id}${titulo ? " · " + titulo : ""}`);
    } else if (id !== idAnterior) {
      registar("vista_livro", { livro_id: id, livro_titulo: titulo });
    }
  }
  function verificarUrl() {
    if (location.href !== urlAnterior) { urlAnterior = location.href; aoMudarPagina(); }
  }
  setInterval(verificarUrl, 1000);
  verificarUrl();

  // pesquisa submetida com Enter numa caixa de pesquisa sem mudar o endereço
  document.addEventListener("keydown", (e) => {
    const t = e.target;
    if (e.key !== "Enter" || !t || !t.matches || !t.matches("input[type=search], input[type=text], input:not([type])")) return;
    const termo = (t.value || "").trim();
    setTimeout(() => { if (!termoDoUrl() && rePesquisa.test(location.pathname + location.search)) novaPesquisa(termo); }, 1200);
  }, true);

  registar("vista_pagina");
})();
