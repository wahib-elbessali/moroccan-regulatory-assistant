const runtimeConfig = globalThis.__APP_CONFIG__;
if (!runtimeConfig) throw new Error("La configuration runtime de l'interface est absente.");

function positiveInteger(value, name) {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1) throw new Error(`Configuration invalide : ${name}.`);
  return parsed;
}

export const MIN_PASSWORD = positiveInteger(runtimeConfig.minPasswordLength, "auth.min_password_length");
export const MAX_QUESTION_CHARS = positiveInteger(runtimeConfig.maxQuestionChars, "agents.max_question_chars");
export const FILE_TYPES = ".pdf,.docx,.html,.md,.txt,.png,.jpg,.jpeg,.tif,.tiff";

export const statusNames = {
  received: { ar: "تم الاستلام", fr: "Reçu" },
  extracting: { ar: "جارٍ الاستخراج", fr: "Extraction" },
  chunked: { ar: "تم تقسيم الوثيقة", fr: "Découpage" },
  indexed: { ar: "جارٍ الفهرسة", fr: "Indexation" },
  ready: { ar: "جاهز", fr: "Prêt" },
  failed: { ar: "تعذرت المعالجة", fr: "Échec" },
};

export const copy = {
  ar: {
    app: "المعين القانوني", tagline: "مساعدك في التنظيمات المغربية", login: "تسجيل الدخول",
    request: "طلب حساب", username: "اسم المستخدم", password: "كلمة المرور", fullName: "الاسم الكامل",
    repeatPassword: "تأكيد كلمة المرور", signIn: "دخول", sendRequest: "إرسال الطلب",
    role: "الدور", lecteur: "قارئ", editeur: "محرر", admin: "مدير النظام",
    chat: "المحادثة", documents: "الوثائق", administration: "الإدارة", overview: "نظرة عامة",
    readerSpace: "فضاء القارئ", editorSpace: "فضاء المحرر", adminSpace: "فضاء الإدارة",
    showNavigation: "إظهار القائمة", hideNavigation: "إخفاء القائمة",
    showHistory: "إظهار سجل المحادثات", hideHistory: "إخفاء سجل المحادثات",
    history: "سجل المحادثات", newConversation: "محادثة جديدة", noHistory: "لا توجد محادثات محفوظة بعد",
    unavailableAnswer: "Cette réponse n'est plus disponible.", unavailableAnswerAr: "هذه الإجابة لم تعد متاحة.",
    deleteConversation: "حذف المحادثة",
    users: "المستخدمون", requests: "طلبات الحساب", web: "البحث في الويب", audit: "سجل التدقيق",
    docRights: "صلاحيات الوثائق", signOut: "تسجيل الخروج", search: "بحث", ready: "جاهز للاستخدام", readyDocs: "وثائق جاهزة",
    askTitle: "ما الذي تبحث عنه؟", askIntro: "اسأل عن القوانين والمراسيم والتنظيمات المغربية.",
    askPlaceholder: "اكتب سؤالك هنا…", send: "إرسال", thinking: "مسار البحث", useWeb: "البحث في الويب",
    sources: "المصادر", confidence: "درجة الثقة", verify: "إجابة مولَّدة آليًا، يُرجى التحقق من المصادر",
    webSource: "مصدر من الويب",
    unknown: "لم أجد هذه المعلومة في الوثائق المتاحة لك.", questionLimit: "السؤال مطلوب، ويجب ألا يتجاوز {max} حرف.",
    docsTitle: "مكتبة الوثائق", docsIntro: "تابع حالة وثائقك وصلاحيات الوصول إليها.", upload: "رفع وثيقة",
    title: "عنوان الوثيقة", source: "المصدر", date: "التاريخ", file: "الملف", chooseFile: "اختر ملفًا",
    visibility: "مستوى الإتاحة", public: "عمومي", internal: "داخلي", private: "خاص · لك فقط",
    uploadAction: "رفع الوثيقة", originalName: "اسم الملف", status: "الحالة", access: "الإتاحة",
    actions: "إجراءات", delete: "حذف", cancel: "إلغاء", confirm: "تأكيد الحذف", noDocs: "لا توجد وثائق بعد",
    deleteWarning: "هل تريد حذف هذه الوثيقة؟ لا يمكن التراجع عن هذا الإجراء.", failedHint: "احذف الوثيقة ثم أعد رفعها.",
    documentServiceError: "تعذرت معالجة الوثيقة بسبب خطأ في إحدى الخدمات. لم يرسل الخادم سببًا أكثر تحديدًا. أعد المحاولة لاحقًا أو اطلب من المسؤول مراجعة سجلات الخادم.",
    documentOcrError: "لم تبلغ جودة التعرّف على النص الحد المطلوب. جرّب ملف PDF نصيًا أو نسخة ممسوحة ضوئيًا أوضح.",
    duplicate: "توجد وثيقة أخرى بالنص نفسه.", justNow: "الآن", recentActivity: "النشاط الأخير",
    adminTitle: "إدارة المنصة", adminIntro: "إدارة الحسابات والصلاحيات وسجل الاستخدام.",
    usersIntro: "إدارة الحسابات الحالية وأدوارها وحالة تفعيلها.",
    requestsIntro: "مراجعة طلبات الحساب المعلقة وتحديد الدور قبل الموافقة.",
    adminDocsIntro: "تحديث صلاحيات وثائق المنصة وحذف وثائق المتن بعد التأكيد.",
    webIntro: "تُطبّق التغييرات على الطلبات الجديدة بعد حفظها عبر الواجهة البرمجية.",
    auditIntro: "سجل الإجراءات الإدارية كما أعادتها الواجهة البرمجية.",
    noUsers: "لا توجد حسابات لعرضها.", noRoles: "لم تُعد الواجهة البرمجية أي أدوار.",
    pendingStatus: "قيد الانتظار", loadingData: "جارٍ تحميل بيانات الإدارة…",
    invalidApiResponse: "استجابة غير مطابقة لعقد الواجهة البرمجية: {endpoint}",
    approveRequestPrompt: "هل تريد الموافقة على طلب الحساب؟", rejectRequestPrompt: "هل تريد رفض طلب الحساب؟",
    confirmApprove: "تأكيد الموافقة", confirmReject: "تأكيد الرفض",
    addUser: "إضافة مستخدم", createUser: "إنشاء حساب", active: "نشط", disabled: "معطّل",
    approve: "موافقة", reject: "رفض", chooseRole: "اختر دورًا", noRequests: "لا توجد طلبات معلقة",
    roleWeb: "البحث في الويب حسب الدور", allowWeb: "السماح بالبحث في الويب", auditEmpty: "لا توجد أحداث مسجلة",
    totalDocs: "الوثائق", pending: "بانتظار المعالجة", accountCount: "الحسابات", activeNow: "النظام يعمل",
    sessionExpired: "انتهت الجلسة. يرجى تسجيل الدخول مجددًا.", unavailable: "الخدمة غير متاحة الآن. حاول مجددًا.",
    interrupted: "انقطع توليد الإجابة. حاول مجددًا.",
    passwordMismatch: "كلمتا المرور غير متطابقتين.", passwordShort: "يجب ألا تقل كلمة المرور عن {min} أحرف.",
    requestSent: "تم إرسال طلبك. سيراجعه أحد المسؤولين.",
    usernameUnavailable: "اسم المستخدم غير متاح.", pendingRequestsFull: "طلبات كثيرة قيد الانتظار. حاول لاحقًا.",
  },
  fr: {
    app: "Assistant réglementaire", tagline: "Les textes marocains, en clair", login: "Connexion",
    request: "Demander un compte", username: "Nom d’utilisateur", password: "Mot de passe", fullName: "Nom complet",
    repeatPassword: "Confirmer le mot de passe", signIn: "Se connecter", sendRequest: "Envoyer la demande",
    role: "Profil", lecteur: "Lecteur", editeur: "Éditeur", admin: "Administrateur",
    chat: "Conversation", documents: "Documents", administration: "Administration", overview: "Vue d’ensemble",
    readerSpace: "ESPACE LECTEUR", editorSpace: "ESPACE ÉDITEUR", adminSpace: "ESPACE ADMINISTRATEUR",
    showNavigation: "Afficher la navigation", hideNavigation: "Masquer la navigation",
    showHistory: "Afficher l’historique", hideHistory: "Masquer l’historique",
    history: "Historique", newConversation: "Nouvelle conversation", noHistory: "Aucune conversation enregistrée.",
    unavailableAnswer: "Cette réponse n'est plus disponible.", unavailableAnswerAr: "هذه الإجابة لم تعد متاحة.",
    deleteConversation: "Supprimer la conversation",
    users: "Utilisateurs", requests: "Demandes de compte", web: "Recherche web", audit: "Journal d’audit",
    docRights: "Droits documentaires", signOut: "Déconnexion", search: "Rechercher",     ready: "Prêt à vous aider", readyDocs: "Documents prêts",
    askTitle: "Que recherchez-vous ?", askIntro: "Interrogez les lois, décrets et textes réglementaires marocains.",
    askPlaceholder: "Posez votre question…", send: "Envoyer", thinking: "Parcours de recherche", useWeb: "Recherche web",
    sources: "Sources", confidence: "Confiance", verify: "Réponse générée, vérifiez les sources",
    webSource: "Source web",
    unknown: "Je n’ai pas trouvé cette information dans les documents qui vous sont accessibles.",
    questionLimit: "La question est requise et ne peut dépasser {max} caractères.",
    docsTitle: "Bibliothèque documentaire", docsIntro: "Suivez le traitement et l’accès à vos documents.", upload: "Ajouter un document",
    title: "Titre du document", source: "Source", date: "Date", file: "Fichier", chooseFile: "Choisir un fichier",
    visibility: "Visibilité", public: "Public", internal: "Interne", private: "Privé · vous seul",
    uploadAction: "Téléverser", originalName: "Nom du fichier", status: "Statut", access: "Visibilité",
    actions: "Actions", delete: "Supprimer", cancel: "Annuler", confirm: "Confirmer la suppression", noDocs: "Aucun document pour l’instant",
    deleteWarning: "Supprimer ce document ? Cette action est irréversible.", failedHint: "Supprimez le document puis téléversez-le à nouveau.",
    documentServiceError: "Un service nécessaire au traitement a échoué. Le serveur n’a pas fourni de cause plus précise. Réessayez plus tard ou demandez à l’administrateur de vérifier les journaux du serveur.",
    documentOcrError: "La reconnaissance du texte n’a pas atteint le seuil de qualité requis. Essayez un PDF avec texte sélectionnable ou un scan plus net.",
    duplicate: "Un document avec le même texte existe déjà.", justNow: "À l’instant", recentActivity: "Activité récente",
    adminTitle: "Administration", adminIntro: "Gérez les comptes, les accès et le journal d’activité.",
    usersIntro: "Gérez les comptes existants, leurs rôles et leur état d’activation.",
    requestsIntro: "Examinez les demandes en attente et choisissez un rôle avant approbation.",
    adminDocsIntro: "Gérez les droits des documents du corpus et leur suppression après confirmation.",
    webIntro: "Les changements sont transmis à l’API et s’appliquent aux prochaines requêtes.",
    auditIntro: "Historique des actions administratives tel que renvoyé par l’API.",
    noUsers: "Aucun compte à afficher.", noRoles: "L’API n’a renvoyé aucun rôle.",
    pendingStatus: "En attente", loadingData: "Chargement des données d’administration…",
    invalidApiResponse: "Réponse incompatible avec le contrat API : {endpoint}",
    approveRequestPrompt: "Confirmer l’approbation de cette demande de compte ?", rejectRequestPrompt: "Confirmer le rejet de cette demande de compte ?",
    confirmApprove: "Confirmer l’approbation", confirmReject: "Confirmer le rejet",
    addUser: "Ajouter un utilisateur", createUser: "Créer le compte", active: "Actif", disabled: "Désactivé",
    approve: "Approuver", reject: "Rejeter", chooseRole: "Choisir un rôle", noRequests: "Aucune demande en attente",
    roleWeb: "Recherche web par rôle", allowWeb: "Autoriser la recherche web", auditEmpty: "Aucun événement enregistré",
    totalDocs: "Documents", pending: "En traitement", accountCount: "Comptes", activeNow: "Système opérationnel",
    sessionExpired: "Session expirée. Veuillez vous reconnecter.", unavailable: "Service indisponible. Réessayez dans un instant.",
    interrupted: "La réponse a été interrompue. Réessayez.",
    passwordMismatch: "Les mots de passe ne correspondent pas.", passwordShort: "Le mot de passe doit comporter au moins {min} caractères.",
    requestSent: "Votre demande a été envoyée. Un administrateur l’examinera.",
    usernameUnavailable: "Ce nom d’utilisateur n’est pas disponible.", pendingRequestsFull: "Trop de demandes sont en attente. Réessayez plus tard.",
  },
};

export const initialDocs = [];

export const roleLabel = (role, translations) => translations[role] || role;
export const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));