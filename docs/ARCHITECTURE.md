# HCF — Architecture

## Principe
Le frontend ne parle **que** l'API HCF (`/api/hc/*`, REST + SSE).
Chaque backend implémente `AdapterInterface` (`server/hcf/adapters/base.py`) :
`list_models()`, `chat_stream()` (générateur d'événements normalisés
`delta/done/error`), `abort()`, `health()`, + `capabilities`
(tools/vision/audio_in/streaming). L'UI s'adapte aux capabilities.

## Sessions
Possédées par HCF (SQLite `data/hcf.sqlite3`) : changer de backend ne perd
jamais l'historique. Contenu normalisé : `text`, `image_url` (data-URL),
`audio` (transcrit en amont sauf backend `audio_in` natif).

## Backends
- **openai_compat** (`adapters/openai_compat.py`) : tout endpoint
  `POST {base}/chat/completions` (Ollama `/v1`, OpenRouter, LM Studio…).
  Instancié 2× : `ollama`, `openrouter` (si clé présente).
- **opencode** (phase 1) : `opencode serve` → sessions/messages/événements ;
  expose `tools=True`.

## Médias (phase 2)
- Vidéo : MediaRecorder → ffmpeg `fps=1` (≤20 frames) + transcript →
  parts multimodales standard (tout backend `vision`).
- Voix : tiers `navigateur` (Web Speech ar-TN) / `local` (faster-whisper) /
  `cloud` (Gemini audio natif) ; réponses TTS via edge-tts `ar-TN`.
