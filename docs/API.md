# HiTech Client — API `/api/hc/*`

Base : `https://client.hitech.tn` (ou `http://<host>:8096`).
**Toute requête exige le token public** : soit `?token=<HCF_PUBLIC_TOKEN>` en query,
soit le cookie `hcf_token` (posé par `/login`). Sans token → `401`.

## Santé & découverte

| Route | Description |
|---|---|
| `GET /api/hc/health` | `{ok: true}` |
| `GET /api/hc/backends` | Backends + capacités : `{id, healthy, capabilities:{tools, vision, audio_in, streaming}}` |
| `GET /api/hc/models?backend=<id>` | Modèles du backend : `{models:[{id, label, vision}]}` |

Backends : `ollama` (local, vision, streaming), `openrouter` (cloud, streaming),
`opencode` (agent tools, providers configurés dans le serve opencode uniquement).

## Sessions

| Route | Description |
|---|---|
| `GET /api/hc/sessions` | Liste : `{sessions:[{id, title, backend, model, created, updated}]}` |
| `POST /api/hc/sessions` | Crée. Body optionnel : `{title?, backend?, model?}` → `{id, ...}` |
| `GET /api/hc/sessions/{sid}` | Détail. `404` si inconnue |
| `PATCH /api/hc/sessions/{sid}` | Renomme… Body : `{title?}` |
| `DELETE /api/hc/sessions/{sid}` | Supprime (liens opencode nettoyés) |
| `GET /api/hc/sessions/{sid}/messages` | Historique : `{messages:[{role, content}]}` |

## Chat

`POST /api/hc/sessions/{sid}/messages`

Body : `{content: string, backend?: string, model?: string, system?: string, images?: [dataURL]}`

- **JSON** (défaut ou `?stream=false`) : `{reply: string, error: string}`
- **SSE** (`?stream=true`) : events `data: {"type":"delta","text":"…"}\n\n`,
  puis `{"type":"done"}` ou `{"type":"error","message":"…"}`.

Erreurs : `400` message vide, `404` session inconnue, `502` backend indisponible
(le détail provider est dans `error`/`message`).

## Médias (préfixe `/api/hc/media`)

| Route | Description |
|---|---|
| `GET /media/voices` | `{tts_voices:["ar-TN-HediNeural","ar-TN-ReemNeural"], stt_tiers:[…]}` |
| `POST /media/transcribe` | multipart `file` + `tier` (`local` \| `gemini`). Gemini → `501` (phase suivante) |
| `POST /media/speak` | JSON `{text, voice?}` → audio MP3. `400` si texte vide |
| `POST /media/video-frames` | multipart `file` (+ `every_s`?) → frames JPEG base64. `422` si vidéo illisible |

## Auth navigateur

- `GET /login` — page token.
- `POST /login` — form `token` → cookie `hcf_token` (HttpOnly) si valide.

## Notes

- CORS autorisé : `capacitor://localhost`, `https://client.hitech.tn`, `https://lab.hitech.tn`.
- Statics UI servis sous `/hc-static/*` (derrière le même gate).
- Config backends : variables d'env dans `.env.service` (jamais commité) —
  voir `server/hcf/config.py` pour les noms (`OPENROUTER_MODEL`, `OC_MODEL`, …).
