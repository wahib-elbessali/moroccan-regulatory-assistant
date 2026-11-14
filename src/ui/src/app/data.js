export const MIN_PASSWORD = 8;
export const MAX_QUESTION_CHARS = 1000;
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
    repeatPassword: "تأكيد كلمة المرور", signIn: "دخول", sendRequest: "إرسال الطلب", demo: "استكشاف العرض التجريبي",
    role: "الدور", lecteur: "قارئ", editeur: "محرر", admin: "مدير النظام", demoHint: "وضع تجريبي · لا يحتاج إلى خادم",
    chat: "المحادثة", documents: "الوثائق", administration: "الإدارة", overview: "نظرة عامة",
    users: "المستخدمون", requests: "طلبات الحساب", web: "البحث في الويب", audit: "سجل التدقيق",
    docRights: "صلاحيات الوثائق", signOut: "تسجيل الخروج", search: "بحث", ready: "جاهز للاستخدام",
    askTitle: "ما الذي تبحث عنه؟", askIntro: "اسأل عن القوانين والمراسيم والتنظيمات المغربية.",
    askPlaceholder: "اكتب سؤالك هنا…", send: "إرسال", thinking: "مسار البحث", useWeb: "البحث في الويب",
    sources: "المصادر", confidence: "درجة الثقة", verify: "إجابة مولَّدة آليًا، يُرجى التحقق من المصادر",
    unknown: "لم أجد هذه المعلومة في الوثائق المتاحة لك.", questionLimit: "السؤال مطلوب، ويجب ألا يتجاوز 1000 حرف.",
    docsTitle: "مكتبة الوثائق", docsIntro: "تابع حالة وثائقك وصلاحيات الوصول إليها.", upload: "رفع وثيقة",
    title: "عنوان الوثيقة", source: "المصدر", date: "التاريخ", file: "الملف", chooseFile: "اختر ملفًا",
    visibility: "مستوى الإتاحة", public: "عمومي", internal: "داخلي", private: "خاص · لك فقط",
    uploadAction: "رفع الوثيقة", originalName: "اسم الملف", status: "الحالة", access: "الإتاحة",
    actions: "إجراءات", delete: "حذف", cancel: "إلغاء", confirm: "تأكيد الحذف", noDocs: "لا توجد وثائق بعد",
    deleteWarning: "هل تريد حذف هذه الوثيقة؟ لا يمكن التراجع عن هذا الإجراء.", failedHint: "احذف الوثيقة ثم أعد رفعها.",
    duplicate: "توجد وثيقة أخرى بالنص نفسه.", justNow: "الآن", recentActivity: "النشاط الأخير",
    adminTitle: "إدارة المنصة", adminIntro: "إدارة الحسابات والصلاحيات وسجل الاستخدام.",
    addUser: "إضافة مستخدم", createUser: "إنشاء حساب", active: "نشط", disabled: "معطّل",
    approve: "موافقة", reject: "رفض", chooseRole: "اختر دورًا", noRequests: "لا توجد طلبات معلقة",
    roleWeb: "البحث في الويب حسب الدور", allowWeb: "السماح بالبحث في الويب", auditEmpty: "لا توجد أحداث مسجلة",
    totalDocs: "الوثائق", pending: "بانتظار المعالجة", accountCount: "الحسابات", activeNow: "النظام يعمل",
    sessionExpired: "انتهت الجلسة. يرجى تسجيل الدخول مجددًا.", unavailable: "الخدمة غير متاحة الآن. حاول مجددًا.",
    passwordMismatch: "كلمتا المرور غير متطابقتين.", passwordShort: "يجب ألا تقل كلمة المرور عن 8 أحرف.",
    requestSent: "تم إرسال طلبك. سيراجعه أحد المسؤولين.",
    usernameUnavailable: "اسم المستخدم غير متاح.", pendingRequestsFull: "طلبات كثيرة قيد الانتظار. حاول لاحقًا.",
  },
  fr: {
    app: "Assistant réglementaire", tagline: "Les textes marocains, en clair", login: "Connexion",
    request: "Demander un compte", username: "Nom d’utilisateur", password: "Mot de passe", fullName: "Nom complet",
    repeatPassword: "Confirmer le mot de passe", signIn: "Se connecter", sendRequest: "Envoyer la demande", demo: "Explorer la démo",
    role: "Profil", lecteur: "Lecteur", editeur: "Éditeur", admin: "Administrateur", demoHint: "Mode démo · aucun serveur requis",
    chat: "Conversation", documents: "Documents", administration: "Administration", overview: "Vue d’ensemble",
    users: "Utilisateurs", requests: "Demandes de compte", web: "Recherche web", audit: "Journal d’audit",
    docRights: "Droits documentaires", signOut: "Déconnexion", search: "Rechercher", ready: "Prêt à vous aider",
    askTitle: "Que recherchez-vous ?", askIntro: "Interrogez les lois, décrets et textes réglementaires marocains.",
    askPlaceholder: "Posez votre question…", send: "Envoyer", thinking: "Parcours de recherche", useWeb: "Recherche web",
    sources: "Sources", confidence: "Confiance", verify: "Réponse générée, vérifiez les sources",
    unknown: "Je n’ai pas trouvé cette information dans les documents qui vous sont accessibles.",
    questionLimit: "La question est requise et ne peut dépasser 1 000 caractères.",
    docsTitle: "Bibliothèque documentaire", docsIntro: "Suivez le traitement et l’accès à vos documents.", upload: "Ajouter un document",
    title: "Titre du document", source: "Source", date: "Date", file: "Fichier", chooseFile: "Choisir un fichier",
    visibility: "Visibilité", public: "Public", internal: "Interne", private: "Privé · vous seul",
    uploadAction: "Téléverser", originalName: "Nom du fichier", status: "Statut", access: "Visibilité",
    actions: "Actions", delete: "Supprimer", cancel: "Annuler", confirm: "Confirmer la suppression", noDocs: "Aucun document pour l’instant",
    deleteWarning: "Supprimer ce document ? Cette action est irréversible.", failedHint: "Supprimez le document puis téléversez-le à nouveau.",
    duplicate: "Un document avec le même texte existe déjà.", justNow: "À l’instant", recentActivity: "Activité récente",
    adminTitle: "Administration", adminIntro: "Gérez les comptes, les accès et le journal d’activité.",
    addUser: "Ajouter un utilisateur", createUser: "Créer le compte", active: "Actif", disabled: "Désactivé",
    approve: "Approuver", reject: "Rejeter", chooseRole: "Choisir un rôle", noRequests: "Aucune demande en attente",
    roleWeb: "Recherche web par rôle", allowWeb: "Autoriser la recherche web", auditEmpty: "Aucun événement enregistré",
    totalDocs: "Documents", pending: "En traitement", accountCount: "Comptes", activeNow: "Système opérationnel",
    sessionExpired: "Session expirée. Veuillez vous reconnecter.", unavailable: "Service indisponible. Réessayez dans un instant.",
    passwordMismatch: "Les mots de passe ne correspondent pas.", passwordShort: "Le mot de passe doit comporter au moins 8 caractères.",
    requestSent: "Votre demande a été envoyée. Un administrateur l’examinera.",
    usernameUnavailable: "Ce nom d’utilisateur n’est pas disponible.", pendingRequestsFull: "Trop de demandes sont en attente. Réessayez plus tard.",
  },
};

export const initialDocs = [
  { doc_id: "doc-public-12", title: "دورية رقم 12 لسنة 2025", source_file: "circulaire_12_2025.pdf", source: "الجريدة الرسمية", date: "2025-03-12", status: "ready", roles: ["lecteur", "editeur"], is_mine: false },
  { doc_id: "doc-internal-07", title: "مذكرة تنظيمية داخلية", source_file: "note_interne_07.pdf", source: "مديرية الشؤون القانونية", date: "2025-06-02", status: "ready", roles: ["editeur"], is_mine: false },
  { doc_id: "doc-processing-31", title: "قرار تنظيمي رقم 31", source_file: "decision_31.pdf", source: "وزارة العدل", date: "2025-09-18", status: "extracting", roles: ["editeur"], is_mine: false },
];

export const initialRequests = [
  { request_id: "req-001", username: "sara.alaoui", full_name: "سارة العلوي", created_at: "2026-11-11T09:32:00Z" },
  { request_id: "req-002", username: "youssef.b", full_name: "يوسف بناني", created_at: "2026-11-11T08:14:00Z" },
];

export const initialUsers = [
  { user_id: "u-01", username: "amina.admin", full_name: "أمينة الإدريسي", role: "admin", is_active: true },
  { user_id: "u-02", username: "mehdi.juriste", full_name: "مهدي المرابط", role: "editeur", is_active: true },
  { user_id: "u-03", username: "noura.lectrice", full_name: "نورة أمين", role: "lecteur", is_active: true },
];

export const roleLabel = (role, translations) => translations[role] || role;
export const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));