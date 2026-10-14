# HiTech Client Framework (HCF)

**Client IA universel — web / desktop / mobile — n'importe quel backend.**

Une UI stable + un core qui parle à **tous** les backends via des *adapters*
interchangeables : OpenCode, Ollama, OpenRouter, LM Studio, vLLM… Nouveau
backend = 1 fichier (~100 lignes). Jamais bloqué sur un seul moteur.

```
apps/web (UI — aussi wrappée en desktop Tauri / mobile Capacitor)
        │  /api/hc/* (REST + SSE, stable)
        ▼
server/hcf (FastAPI) : sessions SQLite · auth · pipeline média
        ▼  AdapterInterface
        ├── adapters/openai_compat.py → Ollama, OpenRouter, LM Studio, vLLM…
        └── adapters/opencode.py      → opencode serve (tools/agents) [phase 1]
```

## Démarrage rapide

```bash
python3 -m venv .venv && .venv/bin/pip install -r server/requirements.txt
HCF_PORT=8096 .venv/bin/python -m uvicorn hcf.app:app --app-dir server \
    --host 127.0.0.1 --port 8096
# → http://127.0.0.1:8096  (UI + API)
```

Variables : `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_VISION_MODEL`,
`OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `HCF_DEFAULT_BACKEND`,
`HCF_DATA_DIR`, `HCF_CORS`, `HCF_PORT`.

## API (extraits)

- `GET /api/hc/health` → backends + capabilities + état
- `GET /api/hc/models?backend=ollama`
- `POST /api/hc/sessions` → `{id}` · `GET /api/hc/sessions`
- `POST /api/hc/sessions/:id/messages` → **SSE** :
  `{"type":"delta","text"}` … `{"type":"done"}` (`?stream=false` → JSON)
- Body message : `{"content": "texte" | [{type:text|image_url,…}], "backend", "model"}`

## Roadmap

- [x] Phase 0 — core + adapter OpenAI-compatible (Ollama/OpenRouter, SSE, vision)
- [ ] Phase 1 — `OpenCodeAdapter` (tools/agents dans la même UI)
- [ ] Phase 2 — médias : record écran → frames+transcript · 🎤 voix (navigateur / whisper local / Gemini audio) + TTS ar-TN
- [ ] Phase 3 — Drive intégré · UI Darija · `lab.hitech.tn/client/`
- [ ] Wrappers Tauri (desktop) + Capacitor (mobile) sur `apps/web`

Voir `docs/ARCHITECTURE.md` et `docs/API.md`.
