# HCF Desktop (Tauri)

Fenêtre native universelle : au lancement, un **écran de connexion** demande
l'adresse du serveur HCF (par défaut `https://client.hitech.tn` — tu peux mettre
ton propre serveur). Le choix est mémorisé, et modifiable à tout moment depuis
l'écran de connexion de l'app (🌐 Serveur).

## Prérequis (build from source)

```bash
sudo apt install libwebkit2gtk-4.1-dev build-essential libssl-dev \
  libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev patchelf
```

## Build

```bash
cd apps/desktop
npm ci
npx tauri build   # → src-tauri/target/release/bundle/{deb,appimage}/…
```

## Comment ça marche

- `launcher.html` (bundled depuis `apps/web/`) : choisit le serveur → navigue
- La fenêtre charge ensuite l'UI du serveur choisi (same-origin, cookies OK)
- Micro + capture d'écran fonctionnent dans la webview
