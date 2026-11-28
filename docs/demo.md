# Demo walkthrough

The exact scenario of the demo, on the demo machine (RTX 3060 Laptop 6 GB, `light` mode). Each
step gives who acts, what they do and what must appear on screen. Every question below was checked
by hand against its reference answer in the evaluation (`evaluation/dataset.jsonl`); use them
exactly as written, and no others.

The internet is off for the whole demo, except the last part (cloud comparison).

## Before the demo

1. At least 10 GB free on `C:`. With a full disk, Docker Desktop stops answering in the middle of
   a question (`docs/hardware.md`).
2. Internet off.
3. From the repository root, in PowerShell, start the stack in `light` mode on the graphics card and
   load the models:

   ```powershell
   $env:MODE="light"; docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --wait; docker compose exec -T api python -m src.core.llm.warmup; $env:MODE=""
   ```

   Do not use `docker compose up -d --wait` alone or `make up-gpu`: both start the `7b`, which does
   not fit on the card next to the other models, and the first question ends at the 60 s limit.
   Wait until the warmup has finished (about two minutes after a start).
4. Sign in once and ask any question, without showing it. The first search after a start loads the
   embedding and re-ranking models (about 30 s); the questions after it take 10 to 20 s.
5. The corpus is already loaded (`make seed`). The administrator account is the one in `.env`.
6. Prepare the private PDF for step 5: a short text-based PDF (not a scan) and one question whose
   answer is in it. Upload it and ask the question once on the demo machine before the demo, then
   delete it.

| Item | Value |
|---|---|
| Administrator account | `ADMIN_USERNAME` / `ADMIN_PASSWORD` from `.env` |
| Reader account | `demo_lecteur`, created in step 2 |
| Editor account | `demo_editeur`, created in the editor part |

## Reader

| No. | User | Action | Expected on screen |
|---:|---|---|---|
| 1 | Presenter | Open `http://localhost:3000`. Switch between « عربي » and « FR » once. | Login screen with the banner « Royaume du Maroc · النصوص التنظيمية », the title « Assistant réglementaire » / « المعين القانوني », and the fields « Nom d'utilisateur » / « اسم المستخدم » and « Mot de passe » / « كلمة المرور ». |
| 2 | New reader | Click « Demander un compte » / « طلب حساب ». Enter `demo_lecteur`, a full name, the password and its confirmation. | After sending: « Votre demande a été envoyée. Un administrateur l'examinera. » / « تم إرسال طلبك. سيراجعه أحد المسؤولين. » |
| 3 | Administrator | Sign in as administrator. Open « Demandes de compte » / « طلبات الحساب ». Choose the `Lecteur` / `قارئ` role, click « Approuver » / « موافقة », then « Confirmer l'approbation ». | The request leaves the pending list and `demo_lecteur` appears under « Utilisateurs ». |
| 4 | Reader | Sign out, sign in as `demo_lecteur`. | Chat screen in « ESPACE LECTEUR » / « فضاء القارئ », with « Conversation » / « المحادثة » and « Documents » / « الوثائق » only. No administration screen. |
| 5 | Reader | Open « Documents », click « Ajouter un document » / « رفع وثيقة », choose the private PDF, enter its title, source and date, click « Téléverser » / « رفع الوثيقة ». | Visibility « Privé · vous seul » / « خاص · لك فقط », then `Reçu` → `Extraction` → `Découpage` → `Indexation` → `Prêt`. |
| 6 | Reader | Open « Conversation » and ask the prepared question about the private PDF. | An answer with `[1]` markers, a « Confiance » / « درجة الثقة » indicator and a citation to the private PDF. |
| 7 | Reader | Ask the questions of the table [Reader questions](#reader-questions), one by one. Open the citation panel for at least one of them. | Each answer contains what the table says, with `[1]` markers and a confidence. The citation panel shows the title, the article and the excerpt. Arabic text reads right to left. |
| 8 | Reader | Switch the interface to « FR » and ask question 1 again. | The Arabic answer stays right to left inside the French interface; the markers stay `[1]`, never `]1[`. |
| 9 | Reader | Ask the two questions of the table [Questions that must get "I don't know"](#questions-that-must-get-i-dont-know). | Both answers are exactly « لم أجد هذه المعلومة في الوثائق المتاحة لك. », with no citation. |
| 10 | Reader | Reload the page, open « Historique » / « سجل المحادثات » and reopen the conversation. | Questions, answers and citations are back. Nothing is asked again. |
| 11 | Administrator | Sign in as administrator. In « Recherche web » / « البحث في الويب », turn web search off for `Lecteur` and save. | One switch per role; the `Lecteur` switch is off. |
| 12 | Reader | Sign in again as `demo_lecteur` and ask question 2. | The « Recherche web » switch is gone from the chat. The answer comes from the documents only. |
| 13 | Administrator | Open « Droits documentaires » / « صلاحيات الوثائق », set `adala_013.pdf` from `Public` to `Interne`, then back to `Public`. Open « Journal d'audit » / « سجل التدقيق ». | Both changes are in the audit log, shown as plain text. Use only `adala_013.pdf`: the documents of the demo questions must stay as they are. |
| 14 | Reader | Open « Documents », click « Supprimer » on the private PDF and confirm. | The confirmation is in the page, not a browser dialog. The document leaves the list. |
| 15 | Presenter | Click « Déconnexion » / « تسجيل الخروج ». | Login screen; nothing of the previous session is left on screen. |

### Reader questions

| No. | Id | Question | The answer must say |
|---:|---|---|---|
| 1 | p1-01 | من يعتبر مغربيا عن طريق النسب أو البنوة وفقا لقانون الجنسية المغربية؟ | the child born of a Moroccan father or a Moroccan mother (الفصل 6, nationality code) |
| 2 | p1-05 | ممن يتكون مجلس العائلة وفقا لأحكام المرسوم رقم 2.04.88؟ | the judge as president, the father and mother (or guardian), and four members from the relatives (المادة الأولى) |
| 3 | p1-07 | كيف يحدد عدد المفوضين القضائيين بدوائر نفوذ المحاكم الابتدائية وفق القانون رقم 46.21؟ | by a decision of the government authority in charge of justice, after consulting the judicial council, the public prosecution and the national body of judicial officers (المادة 11) |
| 4 | p2-06 | ما هو المصدر الرسمي الوحيد لرسوم الحالة المدنية ومستخرجاتها، وأين يمسك؟ | the national civil status register, kept on the central platform of the Ministry of the Interior (المادة 14, law 36.21) |
| 5 | p2-12 | شحال من يوم عند مؤسسة الرعاية الاجتماعية باش تصرح بأي تغيير وقع فـ العناصر اللي تمنحت على أساسها الرخصة؟ | eight days from the change (المادة 17, law 65.15). The question is in Darija; the answer must be in Modern Standard Arabic. |
| 6 | p3-03 | كيف تتكون اللجنة المكلفة بالبحث المنصوص عليها في المادة 16 من القانون رقم 15.01 المتعلق بكفالة الأطفال المهملين؟ | the King's prosecutor (president), the endowments inspector, the local authority and a social worker. Source: المادة الأولى of decree 2.03.600, or the dahir of law 15.01 cited as المادة 17: the dahir quotes the decree's list in a footnote under article 16, and that footnote falls in the article 17 passage. Both are correct. |
| 7 | p6-03 | ما هو المبلغ الشهري للدعم المباشر المخصص للنساء الأرامل في وضعية هشة عن كل طفل يتيم؟ | 350 dirhams per orphan child (المادة 11) |
| 8 | p6-05 | ما هو الأجل الذي يجب أن تبت فيه اللجنة الإقليمية الدائمة في طلبات الدعم المباشر للنساء الأرامل في وضعية هشة؟ | 30 days at most from receiving the request (المادة 7) |
| 9 | p6-06 | كيف يؤدى الدعم المباشر للأرملة المستفيدة؟ | paid into an account opened by the widow at the postal bank near her home, or by any direct means chosen by the competent body (المادة 13) |
| 10 | p6-10 | ما هو المرسوم الذي نسخه المرسوم رقم 2.04.88 بشأن تكوين مجلس العائلة وتحديد مهامه؟ | decree 2.94.31 of 26 December 1994 (المادة التاسعة) |

### Questions that must get "I don't know"

| Id | Question | Why |
|---|---|---|
| p2-13 | ما هو أجل التراجع الممنوح للمستهلك في البيع عن بعد حسب القانون رقم 31.08 المتعلق بتدابير حماية المستهلك؟ | the consumer protection law is not in the corpus |
| p1-11 | ما هي مدة حفظ الوثائق المثبتة لإجراءات تناسب أنظمة الذكاء الاصطناعي وفق مسودة مشروع القانون الداخلي؟ | the answer is only in an internal document, which a reader may not see |

The answer is the same sentence in both cases: the system never says whether the information is
missing or hidden.

## Editor

| No. | User | Action | Expected on screen |
|---:|---|---|---|
| 1 | New editor | Request an account for `demo_editeur`, as in step 2 of the reader part. | « Votre demande a été envoyée. Un administrateur l'examinera. » |
| 2 | Administrator | Approve the request with the `Éditeur` / `محرر` role. | `demo_editeur` appears under « Utilisateurs » with the editor role. |
| 3 | Editor | Sign in as `demo_editeur` and ask p1-11 again (the internal-document question of the reader part). | This time an answer, citing the internal draft law on AI governance. The draft repeats this sentence in several articles with three, five or seven years, so the answer is right when the number matches the article it cites (for example five years, المادة 14). Same question, different role, different result: access control works inside the search. |
| 4 | Editor | Ask p2-05: كم مرة تنعقد اجتماعات لجنة المراقبة في السنة، وما هو أجل توجيه الاستدعاءات إلى أعضائها؟ | Twice a year, and the invitations are sent at least 15 days before the meeting (المادة 8, decree 2.19.693). |
| 5 | Editor | Open « Documents » and click « Ajouter un document ». | The form offers « Public » and « Interne » visibility. A reader's form offers neither. |

## Web search with the internet off

Web search stays on in the settings, but the internet is off. When the system decides to look on
the web, the thinking stream says « لم يُجرَ البحث عبر الويب. » / « Recherche web non effectuée. »,
and the answer comes from the documents only. This is the intended behaviour: nothing leaves the machine.

## Cloud comparison

The only part with the internet on, shown apart from the rest. Only the answer model goes to the
cloud; the narration model, embeddings, re-ranker and OCR stay on the machine.

Before the demo, add these lines to `.env` on the demo machine (the key is never shown on screen):

```
ALLOW_CLOUD_LLM=true
CLOUD_API_BASE=https://integrate.api.nvidia.com/v1
CLOUD_API_KEY=<NVIDIA API key, from build.nvidia.com>
CLOUD_MODEL=nvidia/nemotron-3-ultra-550b-a55b
CLOUD_REASONING_TOKENS=1400
```

`ALLOW_CLOUD_LLM=true` alone sends nothing: the stack also has to be started in `cloud` mode.

To switch to cloud mode, from the repository root, in PowerShell:

```powershell
$env:MODE="cloud"; docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile cloud up -d --wait; docker compose exec -T api python -m src.core.llm.warmup; $env:MODE=""
```

To switch back to `light` mode:

```powershell
docker compose --profile cloud rm -s -f cloud-gateway; $env:MODE="light"; docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --wait; docker compose exec -T api python -m src.core.llm.warmup; $env:MODE=""
```

| No. | User | Action | Expected on screen |
|---:|---|---|---|
| 1 | Reader | Still in `light` mode, ask p4-01: ما السن الذي تكتمل فيه أهلية الزواج وفق مدونة الأسرة؟ | « لم أجد هذه المعلومة في الوثائق المتاحة لك. »: search finds the right article, but the small model does not answer from it. |
| 2 | Presenter | Turn the internet on and switch to cloud mode (command above). | The same interface, the same accounts and the same documents. |
| 3 | Reader | Ask p4-01 again, then reader questions 2 and 6. | p4-01: eighteen full solar years (المادة 19, family code). Questions 2 and 6: the same content as in `light` mode, with the same citations and the same checks. Each answer within 60 s. The difference comes from the larger model, not from the design. |
| 4 | Presenter | Switch back to `light` mode (command above) and turn the internet off. | Back to the offline system. |

## If a step fails

Write down the step, the question, what appeared on screen and the time. Each failure goes to the
part that owns it, to be fixed after the rehearsal. Do not change anything on the machine during
the demo.
