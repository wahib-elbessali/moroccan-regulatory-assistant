# Interface P7

Pile : React 19, Vite et Tailwind CSS 4. Les polices DM Sans et Noto Naskh Arabic sont incluses dans le bundle pour fonctionner hors ligne.

## Organisation

- `src/AppRouter.jsx` déclare les routes et leurs garde-fous d’authentification et de rôle.
- `src/app/AppContext.jsx` porte la session, les préférences et l’état partagé de la démo.
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

Le client suit les routes de `docs/specs/00-shared.md` : `/auth/login`, `/auth/me`, `/auth/account-requests`, `/ask` (SSE), `/documents`, `/documents/{doc_id}/status`, `/admin/users`, `/admin/roles`, `/admin/account-requests`, `/admin/audit` et les mutations `/admin/*` correspondantes.

## Démarrage local

```powershell
cd src/ui
npm install
node .\node_modules\vite\bin\vite.js --host 0.0.0.0
```

Dans ce workspace Windows, le `&` du chemin parent peut interrompre les scripts `npm run`. Appeler Vite directement avec Node évite ce problème. Pour vérifier le bundle : `node .\node_modules\vite\bin\vite.js build`.

Par défaut, l'interface démarre en **mode démo local** : choisissez un rôle sur l'écran de connexion. Aucune API n'est nécessaire et les données de démonstration restent en mémoire.

Pour utiliser l'API P5/P3, lancer Vite avec `VITE_DEMO_MODE=false`. Les appels `/api/*` sont alors transmis à `http://127.0.0.1:8000` par défaut. La cible peut être remplacée avec `API_PROXY_TARGET`. En production, Nginx transmet `/api/` au service `api:8000`.

Les questions et réponses ne sont pas persistées côté interface. Le jeton du mode API est conservé dans `sessionStorage`, jamais dans `localStorage`.