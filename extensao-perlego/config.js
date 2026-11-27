// Configuração partilhada: valores por omissão < chrome.storage.local (página de opções)
// < chrome.storage.managed (política do administrador, p. ex. GPO / Google Admin).
const CONFIG_OMISSAO = {
  servidor: "http://127.0.0.1:8080",
  posto: "",
  chave: "",           // chave de recolha (BIBLIO_CHAVE_RECOLHA no servidor)
  // Endereços da Perlego. Se a Perlego mudar o site, ajuste aqui ou na página de opções.
  regexLivro: "/(?:book|reader)/(\\d+)",
  regexLeitor: "/reader/|[?&](?:reader|read)=|/read(?:/|$)",
  regexPesquisa: "/search(?:/|\\?|$)",
  diagnostico: false,
};

async function lerConfig() {
  const local = await chrome.storage.local.get(Object.keys(CONFIG_OMISSAO));
  let gerida = {};
  try { gerida = await chrome.storage.managed.get(Object.keys(CONFIG_OMISSAO)); } catch (e) { /* sem política */ }
  const cfg = { ...CONFIG_OMISSAO };
  for (const fonte of [local, gerida]) {
    for (const k in fonte) if (fonte[k] !== undefined && fonte[k] !== "") cfg[k] = fonte[k];
  }
  cfg.servidor = String(cfg.servidor).replace(/\/+$/, "");
  return { cfg, gerida };
}
