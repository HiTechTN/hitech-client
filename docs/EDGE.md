# HCF derrière lab.hitech.tn (worker `hitech-store-edge`)

Le worker Cloudflare (dépôt effectif : `/data/hitech-store/edge/`) route :

| Route publique | Destination |
|---|---|
| `lab.hitech.tn/client*` | `https://client.hitech.tn/` (préfixe `/client` retiré) |
| `lab.hitech.tn/api/hc/*` | `https://client.hitech.tn` (tel quel) |
| `lab.hitech.tn/hc-static/*` | `https://client.hitech.tn` (tel quel) |
| `lab.hitech.tn/store*`, `/api/*`, `/static/*`, `/share/*` | HiTech Drive (inchangé) |
| reste | Ghost (inchangé) |

Règles : `/api/hc/` testé AVANT `/api/` ; redirections relatives
côté client re-préfixées `/client` ; `X-Forwarded-Host: lab.hitech.tn`
(les liens générés par HCF suivent via `public_base_url`).

Déploiement : `cd /data/hitech-store/edge && wrangler deploy`
(requiert `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID`).
