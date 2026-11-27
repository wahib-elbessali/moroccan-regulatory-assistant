# Résultats des tests UI

Dernière mise à jour : 2026-11-27

## Suite de tests UI

Commande exécutée depuis `src/ui` le 2026-11-27 :

```powershell
npm.cmd test
```

Résultat : **réussi** — 11 fichiers de test, 56 tests réussis, aucun échec.

## Build de production UI

Commande exécutée depuis `src/ui` :

```powershell
npm.cmd run build
```

Résultat : **réussi** — le bundle de production a été généré.

## Configuration et Nginx

Depuis la racine du projet :

```powershell
docker compose config --quiet
docker compose run --rm --no-deps ui nginx -t
docker compose run --rm --no-deps gateway nginx -t
```

Résultats : **réussi** — Compose est valide et les configurations Nginx de `ui` et `gateway` sont syntaxiquement correctes.

## Application Docker

Image UI reconstruite avec :

```powershell
docker compose build ui
```

Puis `ui` et `gateway` ont été recréés avec :

```powershell
docker compose up -d --no-deps --force-recreate --wait ui gateway
```

Résultat : **réussi** — les deux conteneurs sont démarrés et `healthy`.

## Tests API live

Résultats confirmés :

- `api-live-auth.test.mjs` : 1 test réussi.
- `api-live-account-request.test.mjs` : 1 test réussi.

Les autres tests d’intégration (`api-live-admin`, `api-live-chat`, `api-live-conversations`,
`api-live-upload`) ne sont pas confirmés comme exécutés.
