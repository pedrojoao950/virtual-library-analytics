// Service worker: mantém a sessão, junta o nome do computador e envia os eventos ao servidor.
importScripts("config.js");

const SESSAO_INATIVA_MS = 30 * 60 * 1000;
const MAX_FILA = 3000;

function uid() { return crypto.randomUUID(); }

// Em computadores partilhados não há "utilizador": cada sessão é anónima e independente.
async function sessao(prolongar) {
  const agora = Date.now();
  const { ba_sessao: id, ba_sessao_ultimo: ultimo = 0 } = await chrome.storage.local.get(["ba_sessao", "ba_sessao_ultimo"]);
  if (!prolongar && id) return id;
  const novo = !id || agora - ultimo > SESSAO_INATIVA_MS ? uid() : id;
  await chrome.storage.local.set({ ba_sessao: novo, ba_sessao_ultimo: agora });
  return novo;
}

// Todas as alterações à fila passam por esta cadeia, para não se perderem eventos
// quando chegam várias mensagens ao mesmo tempo.
let cadeia = Promise.resolve();
function serial(fn) { cadeia = cadeia.then(fn, fn); return cadeia; }

let aEnviar = false;
function enfileirar(ev) { return serial(() => _enfileirar(ev)); }
async function _enfileirar(ev) {
  const { cfg } = await lerConfig();
  const evento = { ...ev, ts: ev.ts || Date.now(), sessao: await sessao(ev.tipo !== "presenca") };
  if (cfg.posto) evento.posto = cfg.posto;
  const { ba_fila: fila = [] } = await chrome.storage.local.get("ba_fila");
  fila.push(evento);
  await chrome.storage.local.set({ ba_fila: fila.slice(-MAX_FILA) });
  if (fila.length >= 20 || ev.tipo === "clique_resultado") setTimeout(enviar, 0);
}

async function enviar() {
  if (aEnviar) return;
  aEnviar = true;
  try {
    const { cfg } = await lerConfig();
    const { ba_fila: fila = [] } = await chrome.storage.local.get("ba_fila");
    if (!fila.length) return;
    const lote = fila.slice(0, 500);
    const r = await fetch(cfg.servidor + "/api/eventos", {
      method: "POST", headers: { "Content-Type": "text/plain" }, body: JSON.stringify({ chave: cfg.chave || undefined, eventos: lote }),
    });
    // 400/413: lote inválido, não adianta repetir. 401 (chave errada) fica na fila até corrigir as opções.
    if (r.ok || r.status === 400 || r.status === 413) {
      await serial(async () => {
        const { ba_fila: atual = [] } = await chrome.storage.local.get("ba_fila");
        await chrome.storage.local.set({ ba_fila: atual.slice(lote.length), ba_ultimo_envio: Date.now(), ba_ultimo_erro: "" });
      });
    } else {
      await chrome.storage.local.set({ ba_ultimo_erro: r.status === 401 ? "chave de recolha errada (ver opções)" : `HTTP ${r.status}` });
    }
  } catch (e) {
    await chrome.storage.local.set({ ba_ultimo_erro: String(e.message || e) }); // servidor fora do ar: tenta depois
  } finally {
    aEnviar = false;
  }
}

// Sinal de presença por minuto: o computador está ligado; conta como "em uso" se a Perlego
// estiver no separador ativo e houve atividade de teclado/rato no último 5 min.
async function presenca() {
  let emUso = false;
  try {
    const estado = await chrome.idle.queryState(300);
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    emUso = estado === "active" && !!tab && /^https:\/\/([a-z0-9-]+\.)*perlego\.com\//i.test(tab.url || "");
  } catch (e) { /* sem janela focada */ }
  await enfileirar({ tipo: "presenca", duracao_ms: emUso ? 60000 : 0, pagina: "(computador)" });
  await enviar();
}

chrome.alarms.create("ba_presenca", { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "ba_presenca") presenca(); });
chrome.runtime.onStartup.addListener(presenca);
chrome.runtime.onInstalled.addListener(presenca);

chrome.runtime.onMessage.addListener((msg, _remetente, responder) => {
  if (msg && msg.ba_evento) enfileirar(msg.ba_evento).then(() => responder({ ok: true }));
  else if (msg && msg.ba_enviar) enviar().then(() => responder({ ok: true }));
  return true;
});
