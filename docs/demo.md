# P7 Demo — presentation walkthrough

Objective: verify the complete user journey on the demo machine.

## Preparation before the presentation

- In PowerShell, go to the repository root. On first startup, create `.env` from `.env.example`, enter the secrets, then download the models once with `python services/download_models.py` (Internet required).
- Start the stack from the same directory with `docker compose up -d --wait`. Then check `http://localhost:3000`.
- Prepare a real administrator account in `.env`.

The names and passwords below are placeholders. Replace them with the actual values used on the demo machine.

| Item | Value |
|---|---|
| Administrator account | `<ADMIN_USERNAME>` |
| Administrator password | `<ADMIN_PASSWORD>` |
| Reader account | `demo_lecteur` |
| Reader password | `<DEMO_PASSWORD>` |
| Editor account | `demo_editeur` |
| Editor password | `<DEMO_EDITOR_PASSWORD>` |
| Private PDF | `<DEMO_PRIVATE_PDF>` |
| Public PDF | `<DEMO_PUBLIC_PDF>` |

## Demo walkthrough — Lecteur

| No. | User | Action | Expected on-screen result |
|---:|---|---|---|
| 1 | Presenter | Open `http://localhost:3000`. On the login screen, switch between « عربي » and « FR » if needed. | Secure login screen with the banner « Royaume du Maroc · النصوص التنظيمية », the title « Assistant réglementaire » or « المعين القانوني », and the fields « Nom d’utilisateur » / « اسم المستخدم » and « Mot de passe » / « كلمة المرور ». |
| 2 | New reader | Click « Demander un compte » / « طلب حساب ». Enter `demo_lecteur`, the demo full name, the password, and its confirmation. | « CRÉATION DE COMPTE » form with all four fields. After submission, a green banner appears: « Votre demande a été envoyée. Un administrateur l’examinera. » / « تم إرسال طلبك. سيراجعه أحد المسؤولين. » |
| 3 | Administrator | Sign out if needed, then sign in with the administrator account. Click « Demandes de compte » / « طلبات الحساب ». Select the `Lecteur` / `قارئ` role, click « Approuver » / « موافقة », then « Confirmer l’approbation ». | The `demo_lecteur` request is listed. After approval, it disappears from « Demandes en attente » / « لا توجد طلبات معلقة », and the user appears under « Utilisateurs ». |
| 4 | Lecteur | Sign out from the administrator account. Sign in as `demo_lecteur` with `<DEMO_PASSWORD>`. | Chat screen in « ESPACE LECTEUR » / « فضاء القارئ ». The menu contains « Conversation » / « المحادثة » and « Documents » / « الوثائق ». No administration screen is shown. |
| 5 | Lecteur | Click « Documents », then « Ajouter un document » / « رفع وثيقة ». Select `<DEMO_PRIVATE_PDF>`, enter its title, source, and date, then click « Téléverser » / « رفع الوثيقة ». | The document card shows its name, visibility « Privé · vous seul » / « خاص · لك فقط », and the sequence `Reçu` → `Extraction` → `Découpage` → `Indexation` → `Prêt`. Its final status is « Prêt » / « جاهز ». |
| 6 | Lecteur | Return to « Conversation ». Close the history panel if needed, then ask the prepared question about the private document, for example: `Dans le document privé démontré, quelles dispositions sont applicables et à quelles conditions ?` Then ask this question in Arabic: `ما هي الوثائق التي يمكن الاستناد إليها لدعم التصريح بواقعة الولادة؟` | For the private-document question: an answer with one or more markers `[1]`, `[2]`, a « Confiance » / « درجة الثقة » indicator, and the message « Réponse générée, vérifiez les sources ». The citation panel shows the title, article, page, source, and excerpt. The Arabic question and its answer display correctly from right to left. |
| 7 | Lecteur | Click the icon to hide and then show the conversation history. Click « Nouvelle conversation », then ask the prepared mixed Arabic-French question: `ما هو délai traitement الطلبات الإدارية؟` | Each message remains readable in Arabic or French using `dir="auto"`; citation markers remain isolated as `[1]` and do not appear reversed as `]1[`. |
| 8 | Lecteur | Reload the page, open « Historique » / « سجل المحادثات », then reopen the conversation containing the previous questions. | The history lists conversations with their dates. Questions, answers, and citations are restored, and no new question is added to the conversation history. |
| 9 | Administrator | Sign out from the reader account and start a new session with the administrator account. Go to « Recherche web » / « البحث في الويب ». Disable web search for the `Lecteur` role, then save the change in the panel. | One switch is shown for each role. The switch for `Lecteur` is off. After reloading the reader account, the « Recherche web » control disappears from the chat. |
| 10 | Lecteur | Reload or reopen the reader session. Check the top of the screen and ask another question. | No « Recherche web » switch is visible. The new request is sent with `use_web = false`. |
| 11 | Administrator | Open « Droits documentaires » / « صلاحيات الوثائق », select a corpus document, change its visibility from `Public` to `Interne` or vice versa, then open « Journal d’audit » / « سجل التدقيق ». | The visibility choice is updated in the document list. The audit log shows the recent administrative action and its details as text, without rendering HTML. |
| 12 | Lecteur | Click « Documents », then click « Supprimer » for a demo document and confirm on the page. | An in-page confirmation appears, with no browser dialog. After confirmation, the document disappears from the list. |
| 13 | Presenter | Sign out using « Déconnexion » / « تسجيل الخروج ». | The login screen appears. The current conversation, displayed documents, and entered questions are no longer on screen; signing in again retrieves only the data saved in the API. |

## Demo variation — Éditeur

The chat, history, and answer-viewing steps are the same as for Lecteur. The difference to demonstrate is that Éditeur can choose public visibility when adding a document.

| No. | User | Action | Expected on-screen result |
|---:|---|---|---|
| 1 | New editor | Click « Demander un compte » / « طلب حساب ». Enter `demo_editeur`, the demo full name, the password, and its confirmation. | Confirmation that the account request was sent. |
| 2 | Administrator | In « Demandes de compte » / « طلبات الحساب », select the `Éditeur` / `محرر` role for `demo_editeur`, then approve the request. | The request disappears from the pending requests list, and the user appears under « Utilisateurs » with the Éditeur role. |
| 3 | Éditeur | Sign in as `demo_editeur` with `<DEMO_EDITOR_PASSWORD>`. Open « Documents », add `<DEMO_PUBLIC_PDF>`, enter its title, source, and date, select « Public » visibility, then upload the document. | The upload form offers « Public » and « Interne » visibility options. The document is added with « Public » visibility. |
| 4 | Éditeur | Wait until the document is ready, open « Conversation », and ask a question whose answer is in the public PDF. | The document status is « Prêt ». The answer can cite the public document; the citation panel shows its title and matching excerpt. |


