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
         `${dados.livro_titulo ? ` · ${dados.livro_titulo}${dados.livro_autor ? ` — ${dados.livro_autor}` : ""} (fonte ${dados.titulo_qualidade})` : dados.livro_id ? ` · livro ${dados.livro_id} (sem título)` : ""}` +
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
  // ------------------------------------------------------- identificação dos livros
  // Qualidade da fonte do título (igual à do servidor): 5 JSON-LD, 4 og:title, 3 título do
  // separador, 2 cabeçalho/capa/atributos, 1 texto do link, 0 deduzido do endereço.
  const GENERICOS = new Set(["perlego", "search", "pesquisa", "reader", "leitor", "home", "loading", "loading...",
    "read", "read now", "ler", "ler agora", "start reading", "continue reading", "book", "livro", "ebook", "pdf",
    "epub", "contents", "índice", "table of contents", "cover", "capa", "my library", "untitled"]);
  function limparTitulo(t, autor) {
    if (!t) return null;
    t = String(t).replace(/\s+/g, " ").trim()
      .replace(/\s*[|–—-]\s*Perlego\b.*$/i, "").replace(/^Perlego\s*[|–—:-]\s*/i, "");
    const fmt = "(?:pdf|epub|e-?book|kindle|mobi)";
    for (let i = 0; i < 3; i++) {
      const antes = t;
      t = t.replace(/\s*[-–—|:]?\s*(?:read|ler|leia)\s+(?:online|now|agora|free|grátis)\b.*$/i, "")
        .replace(new RegExp(`\\s*[-–—|:]?\\s*[\\[(]?\\s*${fmt}(?:\\s*(?:and|&|e|/|,)\\s*${fmt})*\\s*[\\])]?\\s*$`, "i"), "")
        .replace(/\s*[-–—|:]\s*$/, "");
      if (t === antes) break;
    }
    if (autor) t = t.replace(new RegExp(`\\s+(?:by|de|por|-|–|—)\\s+${autor.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*$`, "i"), "");
    t = t.replace(/^["'“”‘’«»\s]+|["'“”‘’«»\s]+$/g, "");
    if (t.length < 2 || GENERICOS.has(t.toLowerCase())) return null;
    if (/^(chapter|cap[ií]tulo|part|parte|section|page|página)\s*[\divxlc.]+/i.test(t) && t.length < 40) return null;
    return t.slice(0, 300);
  }
  const textoDe = (el) => (el ? (el.getAttribute("content") || el.textContent || "").trim() : "");
  const nomesAutor = (a) => (Array.isArray(a) ? a : a ? [a] : []).map((x) => (typeof x === "string" ? x : x && x.name) || "").filter(Boolean).join(", ");

  // Dados estruturados (schema.org/Book), que as páginas de livros costumam ter para os motores de busca.
  function livroJsonLd() {
    for (const sc of document.querySelectorAll('script[type="application/ld+json"]')) {
      let dados;
      try { dados = JSON.parse(sc.textContent); } catch (e) { continue; }
      const fila = [dados];
      while (fila.length) {
        const o = fila.shift();
        if (!o || typeof o !== "object") continue;
        if (Array.isArray(o)) { fila.push(...o); continue; }
        if (o["@graph"]) fila.push(...[].concat(o["@graph"]));
        const tipos = [].concat(o["@type"] || []).map(String);
        if (tipos.some((t) => /^(Book|Ebook|EBook|CreativeWork)$/i.test(t)) && o.name) {
          const isbn = o.isbn || (o.workExample && [].concat(o.workExample).map((w) => w && w.isbn).find(Boolean));
          return { titulo: o.name, autor: nomesAutor(o.author), isbn };
        }
        for (const k of ["mainEntity", "itemOffered", "about"]) if (o[k]) fila.push(o[k]);
      }
    }
    return null;
  }

  // Título da página atual (ficha do livro ou leitor), da fonte mais fiável para a menos fiável.
  function infoLivroPagina(noLeitor) {
    const ld = livroJsonLd();
    const autorMeta = textoDe(document.querySelector('meta[name="author"], meta[property="book:author"], meta[name="book:author"]'));
    const autor = (ld && ld.autor) || autorMeta || undefined;
    const isbn = (ld && ld.isbn) || textoDe(document.querySelector('meta[property="book:isbn"], meta[name="isbn"]')) || undefined;
    const fontes = [
      [ld && ld.titulo, 5],
      [textoDe(document.querySelector('meta[property="og:title"], meta[name="twitter:title"]')), 4],
      [document.title, 3],
      // no leitor o <h1> costuma ser o capítulo, por isso só conta na ficha do livro
      [noLeitor ? "" : textoDe(document.querySelector("main h1, h1")), 2],
    ];
    for (const [bruto, qualidade] of fontes) {
      const titulo = limparTitulo(bruto, autor);
      if (titulo) return { titulo, autor, isbn, qualidade };
    }
    return { autor, isbn, qualidade: -1 };
  }

  // Título de um livro a partir de um link (resultados de pesquisa, listas, recomendações).
  function infoLivroLink(a) {
    const cartao = a.closest('li, article, [class*="card" i], [class*="result" i], [class*="item" i]') || a;
    const img = a.querySelector("img[alt]") || cartao.querySelector("img[alt]");
    const cabecalho = a.querySelector("h1,h2,h3,h4,[class*='title' i]") || cartao.querySelector("h2,h3,h4,[class*='title' i]");
    const autorEl = cartao.querySelector("[class*='author' i], [itemprop='author']");
    const autor = autorEl ? autorEl.textContent.trim().replace(/^(by|de|por)\s+/i, "") : undefined;
    const fontes = [
      [cabecalho && cabecalho.textContent, 2],
      [a.getAttribute("title"), 2],
      [a.getAttribute("aria-label"), 2],
      [img && img.getAttribute("alt"), 2],
      [(a.innerText || a.textContent || "").split("\n").map((l) => l.trim()).find((l) => l.length > 1), 1],
    ];
    for (const [bruto, qualidade] of fontes) {
      const titulo = limparTitulo(bruto, autor);
      if (titulo && !/^(by|de|por)\s/i.test(titulo)) return { titulo, autor: autor || undefined, qualidade };
    }
    return tituloDoEndereco(a.getAttribute("href"));
  }

  // Último recurso: /book/123/o-vendedor-de-passados-pdf → "O vendedor de passados" (sem acentos).
  function tituloDoEndereco(href) {
    try {
      const partes = new URL(href, location.href).pathname.split("/").filter(Boolean);
      const i = partes.findIndex((p) => /^\d+$/.test(p));
      const slug = i >= 0 ? partes[i + 1] : null;
      if (!slug || /^\d+$/.test(slug)) return { qualidade: -1 };
      const t = limparTitulo(decodeURIComponent(slug).replace(/-(pdf|epub|ebook|online)$/i, "").replace(/[-_]+/g, " "));
      return t ? { titulo: t.charAt(0).toUpperCase() + t.slice(1), qualidade: 0 } : { qualidade: -1 };
    } catch (e) { return { qualidade: -1 }; }
  }

  // Memória local dos melhores títulos vistos (para o leitor saber o título visto na pesquisa ou na ficha).
  let memoria = {};
  chrome.storage.local.get("ba_livros").then((r) => { memoria = r.ba_livros || {}; }).catch(() => {});
  function lembrar(id, info) {
    if (!id || !info || !info.titulo) return memoria[id] || info;
    const antigo = memoria[id];
    const melhor = !antigo || (info.qualidade ?? 0) >= (antigo.qualidade ?? 0)
      ? { ...antigo, ...info, autor: info.autor || (antigo && antigo.autor), isbn: info.isbn || (antigo && antigo.isbn) }
      : { ...antigo, autor: antigo.autor || info.autor, isbn: antigo.isbn || info.isbn };
    memoria[id] = { ...melhor, visto: Date.now() };
    const ids = Object.keys(memoria);
    if (ids.length > 3000) { // guarda só os 2000 mais recentes
      ids.sort((x, y) => memoria[y].visto - memoria[x].visto).slice(2000).forEach((k) => delete memoria[k]);
    }
    chrome.storage.local.set({ ba_livros: memoria }).catch(() => {});
    return memoria[id];
  }
  const camposLivro = (id, info) => ({
    livro_id: id, livro_titulo: info && info.titulo, livro_autor: info && info.autor,
    livro_isbn: info && info.isbn, titulo_qualidade: info && info.titulo ? info.qualidade : undefined,
  });
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
    for (const a of document.querySelectorAll("a[href]")) { // aprende os títulos de todos os resultados
      const id = idLivro(a.getAttribute("href"));
      if (id && !a.closest("header, nav, footer")) lembrar(id, infoLivroLink(a));
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
    const info = lembrar(id, infoLivroLink(a));
    registar("clique_resultado", {
      ...camposLivro(id, info),
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
    if (leitura.acumulado >= 1000) registar("leitura", { ...camposLivro(leitura.id, leitura.info), duracao_ms: Math.round(leitura.acumulado) });
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
    const noLeitor = reLeitor.test(caminho);
    let info = infoLivroPagina(noLeitor);
    if (!info.titulo) info = { ...tituloDoEndereco(location.href), autor: info.autor, isbn: info.isbn };
    info = lembrar(id, info); // junta com o que já se sabia (p. ex. o título visto nos resultados)
    if (noLeitor) {
      const agora = Date.now();
      leitura = { id, info, acumulado: 0, ultimoTick: agora, ultimoEnvio: agora };
      ultimaInteracao = agora;
      diag(`a ler livro ${id}${info && info.titulo ? ` · ${info.titulo} (fonte ${info.qualidade})` : " · título desconhecido"}`);
    } else if (id !== idAnterior) {
      registar("vista_livro", camposLivro(id, info));
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
