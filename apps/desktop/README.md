# HCF Desktop (Tauri)

Fenêtre native autour du serveur HCF local. Même UI que le web,
micro + capture d'écran fonctionnent dans la webview.

## Prérequis

```bash
sudo apt install libwebkit2gtk-4.1-dev build-essential libssl-dev \
  libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev
```

## Build

```bash
cd apps/desktop
npm i
npx tauri build   # → src-tauri/target/release/bundle/deb/*.deb
```

## Installer / lancer

```bash
sudo dpkg -i "src-tauri/target/release/bundle/deb/HiTech Client_0.1.0_amd64.deb"
hitech-client   # ou via le menu Applications
```

Nécessite `hitech-client.service` actif sur `http://127.0.0.1:8096`
(la fenêtre s'y connecte : login token, chat, médias, Drive).
