# Démo P7 — déroulé de présentation

Objectif : vérifier le parcours utilisateur complet sur le portable de démonstration. Chaque étape précise l’utilisateur, l’action et le résultat attendu à l’écran.

## Préparation avant le public

- Dans PowerShell, se placer à la racine du dépôt. Au premier démarrage, créer `.env` depuis `.env.example`, renseigner les secrets, puis télécharger les modèles une fois avec `python services/download_models.py` (Internet requis).
- Démarrer en mode léger avec le GPU :

  ```powershell
  $env:MODE="light"; docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --wait; docker compose exec -T api python -m src.core.llm.warmup; $env:MODE=""
  ```

- Attendre la fin du warmup des deux modèles avant de poser la première question. Vérifier ensuite `http://localhost:3000`.
- Internet reste déconnecté pendant les étapes locales. Lorsque la recherche Web est activée pour le test hors ligne, le fil de réflexion doit indiquer que la recherche a été ignorée. Internet n'est réactivé que pour la comparaison cloud finale.
- La comparaison cloud nécessite un véritable service cloud configuré et `ALLOW_CLOUD_LLM=true`. Dans la configuration actuelle du dépôt, `cloud-gateway` est un placeholder de développement, pas un service LLM opérationnel : ne pas annoncer la comparaison comme réussie avant de l'avoir configurée et testée.
- Les questions évaluées ci-dessous sont copiées exactement de `evaluation/dataset.jsonl`; garder la recherche Web désactivée sauf pour le test « ignorée ».
- Le jeu retenu ne contient pas de question arabe mêlée à un seul mot français. Pour respecter la consigne de n'utiliser que les questions vérifiées, ne pas improviser ni utiliser l'ancienne question « délai traitement ». Le rendu RTL est vérifié avec la question Darija `p2-12`.

Préparer un compte administrateur réel dans `.env`. Les noms et mots de passe ci-dessous sont des emplacements à remplacer par les valeurs réelles de la machine de démonstration.

| Élément | Valeur |
|---|---|
| Compte administrateur | `<ADMIN_USERNAME>` |
| Mot de passe administrateur | `<ADMIN_PASSWORD>` |
| Compte lecteur | `demo_lecteur` |
| Mot de passe lecteur | `<DEMO_PASSWORD>` |
| Compte éditeur | `demo_editeur` |
| Mot de passe éditeur | `<DEMO_EDITOR_PASSWORD>` |
| PDF privé de répétition | `data/raw/uploads/01_talab_maaloumat_idariya.pdf` |
| PDF public à téléverser par l'éditeur | `<DEMO_PUBLIC_PDF>` |

Le PDF privé indiqué est le fichier de test synthétique présent dans le dépôt. Le téléverser depuis le compte lecteur afin qu'il soit privé à ce compte. **À faire avant la répétition sur le portable de démonstration : confirmer que ce fichier et la question ci-dessous donnent une réponse avec citation.**

## Déroulé — comptes et lecteur

| N° | Utilisateur | Action | Résultat qui doit apparaître à l'écran |
|---:|---|---|---|
| 1 | Présentateur | Ouvrir `http://localhost:3000`. Sur l'écran de connexion, basculer entre « عربي » et « FR » si nécessaire. | Écran sécurisé de connexion avec la bannière « Royaume du Maroc · النصوص التنظيمية », le titre « Assistant réglementaire » ou « المعين القانوني », et les champs « Nom d’utilisateur » / « اسم المستخدم » et « Mot de passe » / « كلمة المرور ». |
| 2 | Nouveau lecteur | Cliquer sur « Demander un compte » / « طلب حساب ». Saisir `demo_lecteur`, le nom complet de démonstration, le mot de passe et sa confirmation. | Formulaire « CRÉATION DE COMPTE ». Après l'envoi, confirmation « Votre demande a été envoyée. Un administrateur l’examinera. » / « تم إرسال طلبك. سيراجعه أحد المسؤولين. » |
| 3 | Administrateur | Se connecter avec le compte administrateur. Ouvrir « Demandes de compte » / « طلبات الحساب », choisir le rôle `Lecteur` / `قارئ` pour `demo_lecteur`, puis approuver et confirmer. | La demande disparaît des demandes en attente et `demo_lecteur` apparaît dans « Utilisateurs ». |
| 4 | Nouvel éditeur | Cliquer sur « Demander un compte » / « طلب حساب ». Saisir `demo_editeur`, le nom complet, le mot de passe et sa confirmation. | Confirmation que la demande de compte a été envoyée. |
| 5 | Administrateur | Dans « Demandes de compte », choisir le rôle `Éditeur` / `محرر` pour `demo_editeur`, puis approuver et confirmer. | La demande disparaît de la liste et `demo_editeur` apparaît dans « Utilisateurs » avec le rôle Éditeur. |
| 6 | Lecteur | Se déconnecter de l'administrateur et se connecter avec `demo_lecteur` et `<DEMO_PASSWORD>`. | Écran de chat dans l'« ESPACE LECTEUR » / « فضاء القارئ ». Le menu contient « Conversation » / « المحادثة » et « Documents » / « الوثائق » ; aucun écran d'administration n'est affiché. |
| 7 | Lecteur | Dans « Documents », ajouter `data/raw/uploads/01_talab_maaloumat_idariya.pdf`, saisir un titre, une source et une date, puis téléverser. | Le document passe par `Reçu` → `Extraction` → `Découpage` → `Indexation` → `Prêt` et indique « Privé · vous seul » / « خاص · لك فقط ». |
| 8 | Lecteur | Dans « Conversation », poser exactement : `ما المعلومات التي يطلبها مقدم الطلب في الملف DEMO-REQ-2048، ومن الجهة المذكورة لتتبع الملف؟` | Réponse citant le PDF privé, indiquant les informations demandées (documents requis et délai d'étude) ainsi que le « مكتب الخدمات الرقمية التجريبي ». Le panneau de citation montre le titre et l'extrait du PDF. **Confirmer ce résultat sur le portable avant la répétition.** |

## Questions évaluées — Lecteur

Pour chaque question, la saisir telle quelle, sans reformulation, et vérifier la présence d'une réponse citée. Les références attendues sont celles de `evaluation/dataset.jsonl`.

| N° | Utilisateur | Action | Résultat qui doit apparaître à l'écran |
|---:|---|---|---|
| 9 | Lecteur | Poser `p1-01` : `من يعتبر مغربيا عن طريق النسب أو البنوة وفقا لقانون الجنسية المغربية؟` | Réponse citant `adala_002.pdf`, الفصل 6. |
| 10 | Lecteur | Poser `p1-02` : `ما هي الوضعية القانونية لجنسية الطفل المولود في المغرب من أبوين مجهولين؟` | Réponse citant `adala_002.pdf`, الفصل 7. |
| 11 | Lecteur | Poser `p1-05` : `ممن يتكون مجلس العائلة وفقا لأحكام المرسوم رقم 2.04.88؟` | Réponse citant `adala_011.pdf`, المادة الأولى. |
| 12 | Lecteur | Poser `p1-07` : `كيف يحدد عدد المفوضين القضائيين بدوائر نفوذ المحاكم الابتدائية وفق القانون رقم 46.21؟` | Réponse citant `sgg_7412.pdf`, المادة 11. |
| 13 | Lecteur | Poser `p2-06` : `ما هو المصدر الرسمي الوحيد لرسوم الحالة المدنية ومستخرجاتها، وأين يمسك؟` | Réponse citant `adala_004.pdf`, المادة 14. |
| 14 | Lecteur | Poser en Darija, sans modification, `p2-12` : `شحال من يوم عند مؤسسة الرعاية الاجتماعية باش تصرح بأي تغيير وقع فـ العناصر اللي تمنحت على أساسها الرخصة؟` | Réponse citant `adala_003.pdf`, المادة 17. Le texte arabe reste lisible de droite à gauche. |
| 15 | Lecteur | Poser `p3-03` : `كيف تتكون اللجنة المكلفة بالبحث المنصوص عليها في المادة 16 من القانون رقم 15.01 المتعلق بكفالة الأطفال المهملين؟` | Réponse citant `adala_012.pdf`, المادة الأولى. |
| 16 | Lecteur | Poser `p6-03` : `ما هو المبلغ الشهري للدعم المباشر المخصص للنساء الأرامل في وضعية هشة عن كل طفل يتيم؟` | Réponse citant `adala_010.pdf`, المادة 11. |
| 17 | Lecteur | Poser `p6-05` : `ما هو الأجل الذي يجب أن تبت فيه اللجنة الإقليمية الدائمة في طلبات الدعم المباشر للنساء الأرامل في وضعية هشة؟` | Réponse citant `adala_010.pdf`, المادة 7. |
| 18 | Lecteur | Poser `p6-06` : `كيف يؤدى الدعم المباشر للأرملة المستفيدة؟` | Réponse citant `adala_010.pdf`, المادة 13. |
| 19 | Lecteur | Poser `p6-10` : `ما هو المرسوم الذي نسخه المرسوم رقم 2.04.88 بشأن تكوين مجلس العائلة وتحديد مهامه؟` | Réponse citant `adala_011.pdf`, المادة التاسعة. |

## Vérification des accès et réponse inconnue

| N° | Utilisateur | Action | Résultat qui doit apparaître à l'écran |
|---:|---|---|---|
| 20 | Lecteur | Poser `p1-11` : `ما هي مدة حفظ الوثائق المثبتة لإجراءات تناسب أنظمة الذكاء الاصطناعي وفق مسودة مشروع القانون الداخلي؟` | Réponse exacte : `لم أجد هذه المعلومة في الوثائق المتاحة لك.` Aucune citation du document interne ne doit apparaître. |
| 21 | Éditeur | Se connecter avec `demo_editeur` et poser exactement la même question, `p1-12`. | Réponse citant le document interne `internal_01_ai_governance.pdf`, المادة 4, avec l'information : `تحفظ الوثائق المثبتة لمدة لا تقل عن ثلاث سنوات.` |
| 22 | Lecteur | Revenir au compte lecteur. Activer « Recherche web » / « البحث في الويب » tout en gardant Internet déconnecté, puis poser `p2-13` : `ما هو أجل التراجع الممنوح للمستهلك في البيع عن بعد حسب القانون رقم 31.08 المتعلق بتدابير حماية المستهلك؟` | Le fil de réflexion indique que la recherche Web a été ignorée (`Recherche Web non effectuée` / `لم يُجرَ البحث عبر الويب`). La réponse finale est `لم أجد هذه المعلومة في الوثائق المتاحة لك.` |
| 23 | Lecteur | Masquer puis réafficher l'historique, ouvrir « Nouvelle conversation », puis recharger la page et rouvrir l'historique. | Les conversations et questions enregistrées sont restaurées ; l'arabe reste en RTL et les citations restent attachées aux réponses. |

## Variante de démonstration — Éditeur et document public

| N° | Utilisateur | Action | Résultat qui doit apparaître à l'écran |
|---:|---|---|---|
| 24 | Éditeur | Se connecter avec `demo_editeur` et poser `p2-05` exactement : `كم مرة تنعقد اجتماعات لجنة المراقبة في السنة، وما هو أجل توجيه الاستدعاءات إلى أعضائها؟` | Réponse citant `adala_009.pdf`, المادة 8. |
| 25 | Éditeur | Dans « Documents », ajouter `<DEMO_PUBLIC_PDF>`, renseigner son titre, sa source et sa date, choisir « Public », puis téléverser et attendre la fin du traitement. | Le document atteint l'état « Prêt » et sa visibilité est indiquée « Public ». |
| 26 | Administrateur | Ouvrir « Droits documentaires » / « صلاحيات الوثائق », changer la visibilité d'un document du corpus entre `Public` et `Interne`, puis ouvrir « Journal d'audit » / « سجل التدقيق ». | La visibilité affichée est mise à jour ; le journal montre l'action et ses détails en texte. |
| 27 | Lecteur | Dans « Documents », vérifier la liste après publication. | **Note de validation :** le backend autorise le lecteur à rechercher les documents publics, mais la page Documents de l'interface peut actuellement les masquer. Ne pas utiliser leur présence dans cette liste comme critère de réussite avant correction de l'interface. |
| 28 | Lecteur | Supprimer le PDF privé de démonstration et confirmer dans la page. | Confirmation dans la page, sans boîte de dialogue du navigateur ; après confirmation, le PDF privé disparaît de la liste. |

## Comparaison cloud — dernière étape

Internet est réactivé uniquement pour cette étape. Utiliser une question vérifiée portant sur un document public, sans document privé.

**Prérequis bloquant :** dans `docker-compose.yml`, le service `cloud-gateway` est actuellement un serveur HTTP placeholder, pas une passerelle LLM. Cette dernière étape ne peut être présentée comme fonctionnelle qu'après configuration d'un véritable fournisseur cloud, activation autorisée (`ALLOW_CLOUD_LLM=true`) et test préalable sur le portable de démonstration.

| N° | Utilisateur | Action | Résultat qui doit apparaître à l'écran |
|---:|---|---|---|
| 29 | Présentateur et Lecteur | Poser exactement la question `p2-06` — `ما هو المصدر الرسمي الوحيد لرسوم الحالة المدنية ومستخرجاتها، وأين يمسك؟` — une fois en mode `light`, puis une fois en mode `cloud`. Afficher ou capturer les deux résultats côte à côte. | Comparaison côte à côte des deux réponses et de leurs citations. Les deux doivent s'appuyer sur la source publique `adala_004.pdf`, المادة 14. Après ce test, couper de nouveau Internet. |


