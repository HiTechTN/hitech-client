/* HiTech Client — universal frontend. Speaks ONLY the stable /api/hc/* API. */
let SID = null, BACKENDS = [], sending = false;

/* API base: same-origin on web/desktop; absolute backend when the UI is
   bundled (Capacitor/file). Override: localStorage["hcf-api"]. */
const HCF_API = (() => {
  try {
    const saved = localStorage.getItem("hcf-api");
    if (saved) return saved.replace(/\/$/, "");
  } catch {}
  const p = (location.protocol || "").toLowerCase();
  if (p === "capacitor:" || p === "file:" || p === "ionic:") {
    return "https://client.hitech.tn";
  }
  return "";
})();

/* ---------- i18n (FR/TN) ---------- */
const STR = {
  fr: { newchat: "＋ Nouvelle conversation", sub: "framework universel",
        ph: "Écris ou dicte ton message… (Entrée = envoyer)",
        drive_title: "📁 HiTech Drive", login_msg: "Accès protégé — entre le token.", copied: "Copié.", need_admin: "Connectez-vous admin sur le Drive d'abord.",
        exported: "Exporté vers le Drive.", empty: "Aucune conversation.", novideo: "Joignez une vidéo d'abord.",
        mp_search: "Chercher un modèle…", free: "GRATUIT", off: "hors ligne",
        w_title: "Salam, chnowa ne3mlou lel youm ?", w_sub: "Ekhtar sujet wela ekteb direct —",
        chips: ["Résume ce texte pour moi", "Aide-moi à écrire un email pro", "Explique-moi ce code", "Donne-moi des idées de contenu", "Traduis en darija"],
        deleted: "🗑 Supprimée", no_models: "Aucun modèle" },
  tn: { newchat: "＋ Conversation jdida", sub: "framework lel kol",
        ph: "Ekteb wela ahki… (Entrée = teb3ath)",
        drive_title: "📁 HiTech Drive", login_msg: "Da5el el token.", copied: "Tnassakh.", need_admin: "Connecti admin fel Drive 9bal.",
        exported: "Tsavvegar fel Drive.", empty: "Ma famma chay.", novideo: "Zid vidéo 9bal.",
        mp_search: "Lawwej 3la modèle…", free: "FREE", off: "off",
        w_title: "Salam, chnowa ne3mlou lel youm ?", w_sub: "Ekhtar sujet wela ekteb direct —",
        chips: ["Sommaire lel texte hedha", "3awni nekteb email pro", "Fahemni el code hedha", "A3tini idées contenu", "Traduji lel darija"],
        deleted: "🗑 Tfasakh", no_models: "Ma famma modèles" },
};
let LANG = localStorage.getItem("hcf-lang") || "fr";
function t(k) { return (STR[LANG] && STR[LANG][k]) || STR.fr[k] || k; }
function applyLang() {
  document.querySelectorAll("[data-i18n]").forEach(el => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll("[data-i18n-ph]").forEach(el => { el.placeholder = t(el.dataset.i18nPh); });
}
function toggleLang() {
  LANG = LANG === "fr" ? "tn" : "fr";
  localStorage.setItem("hcf-lang", LANG);
  applyLang(); refreshSessions();
  const w = $("welcome");
  if (w) { w.remove(); showWelcome(); }
}
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

let HCF_TOKEN = null;
try { HCF_TOKEN = localStorage.getItem("hcf-token"); } catch {}
let USER_TOKEN = null;
try { USER_TOKEN = localStorage.getItem("hcf-user-token"); } catch {}
function hurl(path) {
  let url = HCF_API + path;
  const hasTok = /[?&]token=/.test(url);
  if (HCF_API && HCF_TOKEN && !hasTok) {
    url += (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(HCF_TOKEN);
  }
  return url;
}
function authHeaders() {
  return USER_TOKEN ? { "Authorization": "Bearer " + USER_TOKEN } : {};
}
async function bundleLogin() {
  const v = $("loginToken").value.trim();
  if (!v) return;
  try {
    const r = await fetch(HCF_API + "/api/hc/health?token=" + encodeURIComponent(v));
    if (!r.ok) throw new Error("refusé");
    HCF_TOKEN = v;
    try { localStorage.setItem("hcf-token", v); } catch {}
    $("loginOverlay").classList.add("hidden");
    await boot();
  } catch (e) { $("loginErr").textContent = "Token invalide."; }
}

/* ---------- email + PIN login ---------- */
let loginEmail = "";
async function requestCode() {
  const v = $("loginEmail").value.trim();
  if (!v) { $("loginErr").textContent = "Entre ton email."; return; }
  loginEmail = v;
  $("loginErr").textContent = "";
  try {
    const r = await fetch(HCF_API + "/api/hc/auth/request-code", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: v })
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || r.status);
    $("loginEmailShow").textContent = v;
    $("loginStep1").classList.add("hidden");
    $("loginStep2").classList.remove("hidden");
    $("loginPin").focus();
    if (d.dev_code) $("loginErr").textContent = "(test) code: " + d.dev_code;
  } catch (e) { $("loginErr").textContent = "Erreur: " + e.message; }
}
async function verifyCode() {
  const code = $("loginPin").value.trim();
  if (!code) return;
  $("loginErr").textContent = "";
  try {
    const r = await fetch(HCF_API + "/api/hc/auth/verify", {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: loginEmail, code })
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || r.status);
    USER_TOKEN = d.token;
    try { localStorage.setItem("hcf-user-token", USER_TOKEN); } catch {}
    $("loginOverlay").classList.add("hidden");
    await boot();
  } catch (e) { $("loginErr").textContent = "Erreur: " + e.message; }
}
function loginBack() {
  $("loginStep2").classList.add("hidden");
  $("loginStep1").classList.remove("hidden");
  $("loginErr").textContent = "";
}
function oauthGo(provider) {
  const base = HCF_API || "";
  location.href = `${base}/api/hc/auth/oauth/${provider}/start`;
  return false;
}
async function loadMe() {
  try {
    const r = await fetch(hurl("/api/hc/me"), { credentials: "include", headers: authHeaders() });
    if (!r.ok) return null;
    const d = await r.json();
    $("userEmail").textContent = d.user.email;
    $("userBox").classList.remove("hidden");
    return d.user;
  } catch { return null; }
}
async function userLogout() {
  USER_TOKEN = null;
  try { localStorage.removeItem("hcf-user-token"); } catch {}
  try { await fetch(hurl("/api/hc/auth/logout"), { method: "POST", credentials: "include" }); } catch {}
  location.reload();
}
async function api(path, opts = {}) {
  opts.credentials = "include";
  opts.headers = { ...authHeaders(), ...(opts.headers || {}) };
  const r = await fetch(hurl(path), opts);
  if (!r.ok) { let m = r.status; try { m = (await r.json()).detail || m; } catch {} throw new Error(m); }
  return r.json();
}
function renderParts(parts) {
  return (parts || []).map(p => {
    if (p.type === "text") {
      const t = p.text || "";
      try { return window.marked ? marked.parse(t) : `<pre>${esc(t)}</pre>`; }
      catch { return `<pre>${esc(t)}</pre>`; }
    }
    if (p.type === "image_url") return `<img class="im" src="${esc(p.url)}">`;
    return `<p class="muted">[${esc(p.type)}]</p>`;
  }).join("");
}
function addMsg(role, parts) {
  hideWelcome();
  const d = document.createElement("div");
  d.className = "msg " + role;
  d.innerHTML = renderParts(parts);
  $("msgs").appendChild(d);
  $("msgs").scrollTop = $("msgs").scrollHeight;
  return d;
}

/* ---------- Welcome screen ---------- */
function showWelcome() {
  if ($("msgs").children.length) return;
  const w = document.createElement("div");
  w.id = "welcome";
  w.innerHTML = `
    <div class="w-logo">H</div>
    <h2>${t("w_title")}</h2>
    <p class="muted">${t("w_sub")}</p>
    <div class="chips">${(STR[LANG]?.chips || STR.fr.chips).map(c =>
      `<button class="chip" onclick="useChip(this)">${esc(c)}</button>`).join("")}</div>`;
  $("msgs").appendChild(w);
}
function hideWelcome() { const w = $("welcome"); if (w) w.remove(); }
function useChip(btn) {
  $("input").value = btn.textContent;
  $("input").focus();
}

async function refreshBackends() {
  const d = await api("/api/hc/backends");
  BACKENDS = d.backends || [];
  const ok = BACKENDS.some(b => b.healthy);
  $("connDot").textContent = ok ? "🟢 connecté" : "🔴 hors ligne";
  const sel = $("backendSel");
  sel.innerHTML = BACKENDS.map(b => `<option value="${b.id}">${esc(b.label)}${b.healthy ? "" : " (off)"}</option>`).join("");
  renderBackendSeg();
  sel.onchange = () => { renderBackendSeg(); refreshModels(); };
  await refreshModels();
}
function renderBackendSeg() {
  const cur = $("backendSel").value;
  $("backendSeg").innerHTML = BACKENDS.map(b =>
    `<button class="seg-b ${b.id === cur ? "on" : ""}" onclick="selectBackend('${b.id}')" title="${esc(b.label)}"><span class="dot ${b.healthy ? "ok" : "ko"}"></span>${esc(b.label.split(" ")[0])}</button>`).join("");
}
function selectBackend(id) {
  if ($("backendSel").value === id) return;
  $("backendSel").value = id;
  renderBackendSeg();
  refreshModels();
}

let MODELS = [];
async function refreshModels() {
  const bid = $("backendSel").value;
  const b = BACKENDS.find(x => x.id === bid);
  const caps = [];
  if (b) {
    if (b.capabilities.tools) caps.push("🛠 tools");
    if (b.capabilities.vision) caps.push("👁 vision");
    if (b.capabilities.audio_in) caps.push("🎤 audio");
  }
  $("caps").textContent = caps.join(" · ");
  try {
    const d = await api("/api/hc/models?backend=" + encodeURIComponent(bid));
    MODELS = d.models || [];
  } catch (e) { MODELS = []; }
  $("modelSel").innerHTML = MODELS.map(m => `<option value="${esc(m.id)}">${esc(m.label)}${m.vision ? " 👁" : ""}</option>`).join("");
  renderModelBtn();
  renderModelList("");
}
function shortModel(id) { const p = id.split("/"); return p[p.length - 1] || id; }
function renderModelBtn() {
  const id = $("modelSel").value || shortModel(MODELS[0]?.id || "");
  const m = MODELS.find(x => x.id === id);
  $("modelBtn").innerHTML = `<span class="mbtn-l">${esc(shortModel(id))}</span>${m?.vision ? '<span class="tag vis">👁</span>' : ""}<span class="chev">▾</span>`;
}
function toggleModelPicker(ev) {
  ev.stopPropagation();
  const p = $("modelPicker");
  p.classList.toggle("hidden");
  if (!p.classList.contains("hidden")) {
    $("mpSearch").value = "";
    renderModelList("");
    $("mpSearch").focus();
  }
}
function renderModelList(q) {
  const cur = $("modelSel").value;
  const ql = (q || "").toLowerCase();
  const list = MODELS.filter(m => !ql || m.id.toLowerCase().includes(ql) || (m.label || "").toLowerCase().includes(ql));
  $("mpList").innerHTML = list.map(m =>
    `<div class="mrow ${m.id === cur ? "on" : ""}" onclick="pickModel('${esc(m.id)}')">
      <span class="mrow-name">${esc(shortModel(m.id))}${m.vision ? ' <span class="tag vis">👁</span>' : ""}${m.id.endsWith(":free") ? ` <span class="tag free">${t("free")}</span>` : ""}</span>
      <small class="mrow-sub">${esc(m.label)}</small>
    </div>`).join("") || `<p class="muted mp-empty">${t("no_models")}</p>`;
}
function pickModel(id) {
  $("modelSel").value = id;
  renderModelBtn();
  $("modelPicker").classList.add("hidden");
}
$("mpSearch").addEventListener("input", e => renderModelList(e.target.value));
$("mpSearch").addEventListener("keydown", e => {
  if (e.key === "Enter") { const first = document.querySelector("#mpList .mrow"); if (first) first.click(); }
  if (e.key === "Escape") $("modelPicker").classList.add("hidden");
});
document.addEventListener("click", e => {
  if (!e.target.closest(".mwrap")) $("modelPicker").classList.add("hidden");
});

async function refreshSessions() {
  const d = await api("/api/hc/sessions");
  $("sessions").innerHTML = (d.sessions || []).map(s =>
    `<div class="sess ${s.id === SID ? "on" : ""}" onclick="openSession('${s.id}')" title="${esc(s.backend)} ${esc(s.model)}"><span class="sess-t">${esc(s.title)}<small>${esc(s.backend || "")} · ${new Date(s.updated * 1000).toLocaleDateString()}</small></span><button class="del" onclick="delSession(event,'${s.id}')" title="Supprimer">✕</button></div>`).join("")
    || `<p class="muted">Aucune conversation.</p>`;
}
async function delSession(ev, id) {
  ev.stopPropagation();
  if (!confirm(LANG === "tn" ? "Tfasakh el conversation ?" : "Supprimer cette conversation ?")) return;
  await api(`/api/hc/sessions/${id}`, { method: "DELETE" });
  if (SID === id) { SID = ""; $("msgs").innerHTML = ""; showWelcome(); }
  toast(t("deleted"));
  await refreshSessions();
}
async function newSession() {
  const s = await api("/api/hc/sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ backend: $("backendSel").value, model: $("modelSel").value }) });
  SID = s.id; $("msgs").innerHTML = "";
  showWelcome();
  await refreshSessions();
}
async function openSession(id) {
  SID = id; $("msgs").innerHTML = "";
  const d = await api(`/api/hc/sessions/${id}/messages`);
  for (const m of (d.messages || [])) addMsg(m.role, m.content);
  if (!document.querySelector("#msgs .msg")) showWelcome();
  await refreshSessions();
}
let pendingImages = [];
let ttsOn = false;

function showPending() {
  const p = $("pending");
  const n = pendingImages.length + pendingAttach.length;
  if (!n) { p.classList.add("hidden"); p.textContent = ""; return; }
  p.classList.remove("hidden");
  p.textContent = `📎 ${n} pièce(s) jointe(s) avec le message (✕ pour retirer)`;
  p.style.cursor = "pointer";
  p.onclick = () => { pendingImages = []; pendingAttach = []; showPending(); };
}

function attachVideo() { $("vidFile").click(); }
$("vidFile").addEventListener("change", async () => {
  const f = $("vidFile").files[0];
  if (!f) return;
  const btn = $("vidBtn"); btn.disabled = true; btn.textContent = "⏳";
  try {
    const fd = new FormData();
    fd.append("file", f); fd.append("fps", "1"); fd.append("max_frames", "20");
    const r = await fetch(hurl("/api/hc/media/video-frames"), { method: "POST", credentials: "include", headers: authHeaders(), body: fd });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const d = await r.json();
    pendingImages = (d.frames || []).map(x => ({ type: "image_url", url: x.url }));
    if (!pendingImages.length) throw new Error("aucune image extraite");
    showPending();
    if (!$("input").value.trim()) $("input").value = "Voici des images de ma vidéo, ";
    $("input").focus();
  } catch (e) { alert("Vidéo: " + e.message); }
  btn.disabled = false; btn.textContent = "🎥";
  $("vidFile").value = "";
});

let rec = null, recChunks = [];
async function dictate() {
  const btn = $("micBtn");
  if (rec) { rec.stop(); return; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recChunks = [];
    rec = new MediaRecorder(stream, { mimeType: MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "" });
    rec.ondataavailable = e => { if (e.data.size) recChunks.push(e.data); };
    rec.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      btn.classList.remove("rec"); btn.textContent = "🎤"; btn.disabled = true;
      try {
        const blob = new Blob(recChunks, { type: rec.mimeType || "audio/webm" });
        const fd = new FormData();
        fd.append("file", blob, "dictation.webm"); fd.append("tier", "local"); fd.append("lang", "ar");
        btn.textContent = "⏳";
        const r = await fetch(hurl("/api/hc/media/transcribe"), { method: "POST", credentials: "include", headers: authHeaders(), body: fd });
        if (!r.ok) throw new Error("HTTP " + r.status);
        const d = await r.json();
        $("input").value = ($("input").value ? $("input").value + " " : "") + (d.text || "");
        $("input").focus();
      } catch (e) { alert("Dictée: " + e.message); }
      btn.disabled = false; btn.textContent = "🎤"; rec = null;
    };
    rec.start();
    btn.classList.add("rec"); btn.textContent = "⏹";
  } catch (e) { alert("Micro inaccessible: " + e.message); }
}

function toggleTTS() {
  ttsOn = !ttsOn;
  $("ttsBtn").classList.toggle("off", !ttsOn);
  if (!ttsOn) { $("ttsAudio").pause(); }
}
async function speakText(text) {
  try {
    const r = await fetch(hurl("/api/hc/media/speak"), {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ text: text.slice(0, 1500) })
    });
    if (!r.ok) return;
    const blob = await r.blob();
    const a = $("ttsAudio");
    a.src = URL.createObjectURL(blob);
    await a.play().catch(() => {});
  } catch {}
}
function plainText(parts) {
  return (parts || []).filter(p => p.type === "text").map(p => p.text).join(" ")
    .replace(/[#*`>|[\]()]/g, "").slice(0, 1500);
}

async function send() {
  if (sending) return;
  const text = $("input").value.trim();
  if (!text && !pendingImages.length && !pendingAttach.length) return;
  if (!SID) await newSession();
  $("input").value = "";
  const parts = [...pendingImages, ...pendingAttach];
  if (text) parts.push({ type: "text", text });
  pendingImages = []; pendingAttach = []; showPending();
  addMsg("user", parts);
  sending = true;
  const box = addMsg("assistant", [{ type: "text", text: "…" }]);
  try {
    const r = await fetch(hurl(`/api/hc/sessions/${SID}/messages`), {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ content: parts, backend: $("backendSel").value, model: $("modelSel").value })
    });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "", full = "";
    const render = () => { try { box.innerHTML = window.marked ? marked.parse(full) : `<pre>${esc(full)}</pre>`; } catch { box.innerHTML = `<pre>${esc(full)}</pre>`; } $("msgs").scrollTop = $("msgs").scrollHeight; };
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const frames = buf.split("\n\n"); buf = frames.pop();
      for (const f of frames) {
        const line = f.trim();
        if (!line.startsWith("data:")) continue;
        try {
          const ev = JSON.parse(line.slice(5));
          if (ev.type === "delta" && ev.text) { full += ev.text; render(); }
          else if (ev.type === "error") { full += `\n\n> ⚠ ${ev.message}`; render(); }
        } catch {}
      }
    }
    if (!full.trim()) box.innerHTML = `<p class="muted">(réponse vide)</p>`;
    else if (ttsOn) speakText(full);
  } catch (e) { box.innerHTML = `<p class="muted">Erreur: ${esc(e.message)}</p>`; }
  sending = false;
  refreshSessions();
}
$("input").addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});
async function boot() {
  applyLang();
  try { await refreshBackends(); } catch (e) { $("connDot").textContent = "🔴 " + e.message; }
  await refreshSessions();
  showWelcome();
}
(async () => {
  applyLang();
  let authed = false;
  try {
    const r = await fetch(hurl("/api/hc/backends"), { credentials: "include", headers: authHeaders() });
    authed = r.ok;
  } catch {}
  if (!authed) { $("loginOverlay").classList.remove("hidden"); return; }
  await boot();
  loadMe();
})();

/* ---------- HiTech Drive integration ---------- */
const DRIVE_BASE = "https://lab.hitech.tn";
let drivePath = "", pendingAttach = [];
const TEXT_EXTS = ["txt", "md", "markdown", "py", "js", "ts", "json", "yaml", "yml", "toml", "sh", "log", "csv", "css", "html", "xml", "sql", "c", "h", "cpp", "java", "go", "rs", "php", "ini", "conf"];

function toast(msg) {
  const el = document.createElement("div");
  el.className = "toast"; el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 2600);
}
function openDrive() { $("driveModal").classList.remove("hidden"); driveBrowse(""); }
function closeDrive() { $("driveModal").classList.add("hidden"); }
async function driveBrowse(path) {
  drivePath = path;
  $("driveMsg").textContent = "";
  try {
    const r = await fetch(DRIVE_BASE + "/api/drive/list?path=" + encodeURIComponent(path), { credentials: "include" });
    if (!r.ok) throw new Error(r.status === 403 ? t("need_admin") : "HTTP " + r.status);
    const d = await r.json();
    $("driveCrumbs").innerHTML = (d.breadcrumbs || []).map((c, i) =>
      (i ? "<span>›</span>" : "") + `<a onclick="driveBrowse('${esc(c.path)}')">${esc(c.name)}</a>`).join("");
    let html = "";
    for (const dir of (d.dirs || []))
      html += `<div class="drow"><span>📁 ${esc(dir.name)}</span><button class="btn ghost" onclick="driveBrowse('${esc(dir.path)}')">Ouvrir</button></div>`;
    for (const f of (d.files || []))
      html += `<div class="drow"><span>${esc(f.name)} <span class="muted">${esc(f.size_str || "")}</span></span><button class="btn ghost" onclick='driveAttach(${JSON.stringify(f.path)},${JSON.stringify(f.name)})'>➕ Joindre</button></div>`;
    $("driveList").innerHTML = html || `<p class="muted">${t("empty")}</p>`;
  } catch (e) { $("driveMsg").textContent = "Drive: " + e.message; }
}
async function driveAttach(path, name) {
  $("driveMsg").textContent = "…";
  try {
    const ext = (name.split(".").pop() || "").toLowerCase();
    const url = DRIVE_BASE + "/api/drive/download?path=" + encodeURIComponent(path);
    if (TEXT_EXTS.includes(ext)) {
      const r = await fetch(url, { credentials: "include" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const txt = (await r.text()).slice(0, 60000);
      pendingAttach.push({ type: "text", text: `[Drive: ${path}]\n${txt}\n[/Drive]` });
    } else if (["png", "jpg", "jpeg", "gif", "webp"].includes(ext)) {
      const r = await fetch(url, { credentials: "include" });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const blob = await r.blob();
      const dataUrl = await new Promise(res => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(blob); });
      pendingImages.push({ type: "image_url", url: dataUrl });
    } else {
      pendingAttach.push({ type: "text", text: `[Drive: ${name}](${url})` });
    }
    showPending(); closeDrive(); toast("➕ " + name);
  } catch (e) { $("driveMsg").textContent = "Drive: " + e.message; }
}
function sessMarkdown() {
  return [...document.querySelectorAll("#msgs .msg")].map(m =>
    (m.classList.contains("user") ? "**Moi:** " : "**Assistant:** ") +
    (m.innerText || "").slice(0, 4000)).join("\n\n---\n\n");
}
async function exportToDrive() {
  if (!SID) return;
  const title = (document.querySelector(".sess.on")?.firstChild?.textContent || "conversation").trim().slice(0, 60) || "conversation";
  const fname = title.toLowerCase().replace(/[^a-z0-9]+/gi, "-").slice(0, 50) + ".md";
  const body = `# ${title}\n\nExporté de HiTech Client\n\n` + sessMarkdown();
  try {
    await fetch(DRIVE_BASE + "/api/drive/mkdir", {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ parent: "public", name: "HCF-exports" })
    });
    const fd = new FormData();
    fd.append("folder", "public/HCF-exports");
    fd.append("paths", JSON.stringify([fname]));
    fd.append("files", new Blob([body], { type: "text/markdown" }), fname);
    const r = await fetch(DRIVE_BASE + "/api/drive/upload-batch", { method: "POST", credentials: "include", body: fd });
    if (!r.ok) throw new Error(r.status === 403 ? t("need_admin") : "HTTP " + r.status);
    toast("💾 " + t("exported"));
  } catch (e) { toast("Drive: " + e.message); }
}
