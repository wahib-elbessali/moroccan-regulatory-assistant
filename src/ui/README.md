# Interface P7

Pile : React 19, Vite et Tailwind CSS 4. Les polices DM Sans et Noto Naskh Arabic sont incluses dans le bundle pour fonctionner hors ligne.

## Organisation

- `src/AppRouter.jsx` déclare les routes et leurs garde-fous d’authentification et de rôle.
- `src/app/AppContext.jsx` porte la session, les préférences et l’état partagé de l’interface.
- `src/pages/auth/` contient les pages distinctes de connexion et de demande de compte.
- `src/pages/chat/ChatPage.jsx` utilise `src/components/ChatView.jsx`, le chat partagé par `lecteur` et `editeur`.
- `src/pages/documents/DocumentsPage.jsx` gère les documents et adapte les actions au rôle.
- `src/pages/admin/AdminRoutes.jsx` contient les pages et les données partagées de l’administration.
- `src/components/WorkspaceLayout.jsx` fournit la navigation et le cadre commun des espaces connectés.
- `src/api.js` centralise Axios, le jeton et les contrats HTTP. Les écrans appellent les méthodes nommées `api.auth`, `api.ask`, `api.documents` et `api.admin`, et ne construisent pas directement les URLs.

## Routes

| Route | Accès |
|---|---|
| `/login` | Public |
| `/demande-compte` | Public |
| `/lecteur/chat`, `/lecteur/documents` | `lecteur` |
| `/editeur/chat`, `/editeur/documents` | `editeur` |
| `/admin`, `/admin/users`, `/admin/requests`, `/admin/documents`, `/admin/web`, `/admin/audit` | `admin` |

Le client suit les routes de `docs/specs/00-shared.md` : `/auth/login`, `/auth/me`, `/auth/account-requests`, `/ask` (SSE), `/conversations` (historique sauvegardé par l'API), `/documents`, `/documents/{doc_id}/status`, `/admin/users`, `/admin/roles`, `/admin/account-requests`, `/admin/audit` et les mutations `/admin/*` correspondantes.

## Démarrage local

```powershell
cd src/ui
npm install
node .\node_modules\vite\bin\vite.js --host 0.0.0.0
```

Dans ce workspace Windows, le `&` du chemin parent peut interrompre les scripts `npm run`. Appeler Vite directement avec Node évite ce problème. L’API doit être démarrée avant d’utiliser l’interface. Pour vérifier le bundle : `node .\node_modules\vite\bin\vite.js build`.

Les tests UI sont dans `tests/ui` et se lancent depuis `src/ui` avec `node .\node_modules\vitest\vitest.mjs run`.

L’interface fonctionne uniquement avec l’API : connexion, conversations, documents et administration utilisent les routes HTTP. Aucun rôle ni contenu fictif n’est fourni localement. Les appels `/api/*` sont transmis à `http://127.0.0.1:8000` par défaut. La cible peut être remplacée avec `API_PROXY_TARGET`. Dans Compose, Nginx transmet `/api/` au service `api:8000` et sert l’application sur le port 3000.

Les tests d’intégration API réelle sont séparés des tests UI simulés et ne sont pas exécutés par Vitest. Démarrez l’API, puis lancez-les depuis `src/ui` avec les identifiants chargés depuis le `.env` de la racine :

```powershell
node --env-file=..\..\.env --test `
  ..\..\tests\ui\api-live-auth.test.mjs `
  ..\..\tests\ui\api-live-account-request.test.mjs `
  ..\..\tests\ui\api-live-admin.test.mjs `
  ..\..\tests\ui\api-live-chat.test.mjs `
  ..\..\tests\ui\api-live-conversations.test.mjs `
  ..\..\tests\ui\api-live-upload.test.mjs
```

Par défaut, `ADMIN_USERNAME` et `ADMIN_PASSWORD` du `.env` servent aux tests admin, auth et upload privé. Pour les tests de chat et d’historique, fournissez aussi `LIVE_API_USERNAME` et `LIVE_API_PASSWORD` pour un compte `lecteur` ou `editeur`. La suite sauvegarde et supprime ses conversations et son document de test; la demande de compte utilise le nom d’utilisateur déjà authentifié pour vérifier `409` sans créer de demande.

Correspondance des tests live avec P7 :

- `api-live-auth.test.mjs` : P7-09/10, connexion et profil réel.
- `api-live-account-request.test.mjs` : P7-13/14, réponse `409` pour un nom déjà utilisé, sans création de demande.
- `api-live-admin.test.mjs` : P7-29, lecture des collections d’administration.
- `api-live-chat.test.mjs` : P7-15/19, requête réelle `/ask` et fin SSE `done`.
- `api-live-conversations.test.mjs` : P7-22/22b, création, liste, sauvegarde, lecture et suppression d’une conversation.
- `api-live-upload.test.mjs` : P7-23/25/27, upload multipart, suivi de statut et suppression du document de test.

Dans Compose, le conteneur UI lit `auth.min_password_length` et `agents.max_question_chars` depuis `/app/config.yaml` au démarrage et publie uniquement ces deux limites dans `runtime-config.js`. En développement local, ce fichier sert les valeurs par défaut de `config.yaml`.

Les questions et réponses sont sauvegardées uniquement via `/conversations`; elles ne sont pas copiées dans le stockage navigateur. Le jeton est conservé dans `sessionStorage`, jamais dans `localStorage`.