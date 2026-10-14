/* HiTech Client — universal frontend. Speaks ONLY the stable /api/hc/* API. */
let SID = null, BACKENDS = [], sending = false;
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
  if (!pendingImages.length) { p.classList.add("hidden"); p.textContent = ""; return; }
  p.classList.remove("hidden");
  p.textContent = `🎥 ${pendingImages.length} image(s) de la vidéo seront envoyées avec le message (✕ pour retirer)`;
  p.style.cursor = "pointer";
  p.onclick = () => { pendingImages = []; showPending(); };
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
  if (!text && !pendingImages.length) return;
  if (!SID) await newSession();
  $("input").value = "";
  const parts = [...pendingImages];
  if (text) parts.push({ type: "text", text });
  pendingImages = []; showPending();
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
(async () => { try { await refreshBackends(); } catch (e) { $("connDot").textContent = "🔴 " + e.message; } await refreshSessions(); })();
