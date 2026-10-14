/* HiTech Client — universal frontend. Speaks ONLY the stable /api/hc/* API. */
let SID = null, BACKENDS = [], sending = false;

/* ---------- i18n (FR/TN) ---------- */
const STR = {
  fr: { newchat: "＋ Nouvelle conversation", sub: "framework universel",
        ph: "Écris ou dicte ton message… (Entrée = envoyer)",
        drive_title: "📁 HiTech Drive", copied: "Copié.", need_admin: "Connectez-vous admin sur le Drive d'abord.",
        exported: "Exporté vers le Drive.", empty: "Aucune conversation.", novideo: "Joignez une vidéo d'abord." },
  tn: { newchat: "＋ Conversation jdida", sub: "framework lel kol",
        ph: "Ekteb wela ahki… (Entrée = teb3ath)",
        drive_title: "📁 HiTech Drive", copied: "Tnassakh.", need_admin: "Connecti admin fel Drive 9bal.",
        exported: "Tsavvegar fel Drive.", empty: "Ma famma chay.", novideo: "Zid vidéo 9bal." },
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
}
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
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
  const d = document.createElement("div");
  d.className = "msg " + role;
  d.innerHTML = renderParts(parts);
  $("msgs").appendChild(d);
  $("msgs").scrollTop = $("msgs").scrollHeight;
  return d;
}

async function refreshBackends() {
  const d = await api("/api/hc/backends");
  BACKENDS = d.backends || [];
  const ok = BACKENDS.some(b => b.healthy);
  $("connDot").textContent = ok ? "🟢 connecté" : "🔴 hors ligne";
  const sel = $("backendSel");
  sel.innerHTML = BACKENDS.map(b => `<option value="${b.id}">${esc(b.label)}${b.healthy ? "" : " (off)"}</option>`).join("");
  sel.onchange = refreshModels;
  await refreshModels();
}
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
    $("modelSel").innerHTML = (d.models || []).map(m => `<option value="${esc(m.id)}">${esc(m.label)}${m.vision ? " 👁" : ""}</option>`).join("");
  } catch (e) { $("modelSel").innerHTML = ""; }
}

async function refreshSessions() {
  const d = await api("/api/hc/sessions");
  $("sessions").innerHTML = (d.sessions || []).map(s =>
    `<div class="sess ${s.id === SID ? "on" : ""}" onclick="openSession('${s.id}')" title="${esc(s.backend)} ${esc(s.model)}">${esc(s.title)}<small>${esc(s.backend || "")} · ${new Date(s.updated * 1000).toLocaleDateString()}</small></div>`).join("")
    || `<p class="muted">Aucune conversation.</p>`;
}
async function newSession() {
  const s = await api("/api/hc/sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ backend: $("backendSel").value, model: $("modelSel").value }) });
  SID = s.id; $("msgs").innerHTML = "";
  await refreshSessions();
}
async function openSession(id) {
  SID = id; $("msgs").innerHTML = "";
  const d = await api(`/api/hc/sessions/${id}/messages`);
  for (const m of (d.messages || [])) addMsg(m.role, m.content);
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
    const r = await fetch("/api/hc/media/video-frames", { method: "POST", body: fd });
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
        const r = await fetch("/api/hc/media/transcribe", { method: "POST", body: fd });
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
    const r = await fetch("/api/hc/media/speak", {
      method: "POST", headers: { "Content-Type": "application/json" },
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
    const r = await fetch(`/api/hc/sessions/${SID}/messages`, {
      method: "POST", headers: { "Content-Type": "application/json" },
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
(async () => { applyLang(); try { await refreshBackends(); } catch (e) { $("connDot").textContent = "🔴 " + e.message; } await refreshSessions(); })();

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
