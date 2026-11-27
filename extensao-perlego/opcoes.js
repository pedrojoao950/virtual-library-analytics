const CAMPOS = Object.keys(CONFIG_OMISSAO);

async function mostrar() {
  const local = await chrome.storage.local.get(CAMPOS);
  const { cfg, gerida } = await lerConfig();
  for (const k of CAMPOS) {
    const el = document.getElementById(k);
    if (!el) continue;
    if (el.type === "checkbox") el.checked = !!cfg[k];
    else el.value = k in gerida ? cfg[k] : (local[k] ?? CONFIG_OMISSAO[k]);
    el.disabled = k in gerida;
    if (k in gerida) el.title = "Definido pelo administrador";
  }
  await estado(cfg);
}

async function estado(cfg) {
  const { ba_fila: fila = [], ba_ultimo_envio: ultimo, ba_ultimo_erro: erro } =
    await chrome.storage.local.get(["ba_fila", "ba_ultimo_envio", "ba_ultimo_erro"]);
  let ligacao = "";
  try {
    const r = await fetch(cfg.servidor + "/api/saude", { cache: "no-store" });
    ligacao = r.ok ? "✓ servidor contactável" : `✗ servidor respondeu ${r.status}`;
    if (r.ok) { // testa a chave de recolha com um envio vazio
      const t = await fetch(cfg.servidor + "/api/eventos", { method: "POST", headers: { "Content-Type": "text/plain" },
        body: JSON.stringify({ chave: cfg.chave || undefined, eventos: [] }) });
      ligacao += t.status === 401 ? "\n✗ chave de recolha errada ou em falta" : t.ok ? "\n✓ chave de recolha aceite" : "";
    }
  } catch (e) {
    ligacao = "✗ não foi possível contactar o servidor";
  }
  document.getElementById("estado").textContent =
    `${ligacao}\nEventos à espera de envio: ${fila.length}` +
    (ultimo ? `\nÚltimo envio: ${new Date(ultimo).toLocaleString()}` : "") +
    (erro ? `\nÚltimo erro: ${erro}` : "");
}

document.getElementById("guardar").addEventListener("click", async () => {
  const novo = {};
  for (const k of CAMPOS) {
    const el = document.getElementById(k);
    if (!el || el.disabled) continue;
    novo[k] = el.type === "checkbox" ? el.checked : el.value.trim();
  }
  for (const k of ["regexLivro", "regexLeitor", "regexPesquisa"]) {
    try { new RegExp(novo[k] || CONFIG_OMISSAO[k]); } catch (e) {
      document.getElementById("estado").textContent = `Expressão inválida em “${k}”: ${e.message}`;
      return;
    }
  }
  await chrome.storage.local.set(novo);
  await mostrar();
  document.getElementById("estado").textContent = "Guardado. Recarregue as páginas da Perlego abertas.\n" + document.getElementById("estado").textContent;
});

mostrar();
