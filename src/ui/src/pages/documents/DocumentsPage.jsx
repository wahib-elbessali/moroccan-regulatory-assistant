import { useState } from "react";
import { Activity, CheckCircle2, CircleAlert, Clock3, FilePlus2, FileText, Trash2, Upload, X } from "lucide-react";
import { api } from "../../api.js";
import { useApp } from "../../app/AppContext.jsx";
import { copy, FILE_TYPES, pause, statusNames } from "../../app/data.js";
import { Button, Field, Metric, StatusPill } from "../../components/Ui.jsx";

function documentErrorMessage(error, translations) {
  if (error === "ServiceError") return translations.documentServiceError;
  if (error === "OCR quality too low") return translations.documentOcrError;
  return error || translations.failedHint;
}

export default function DocumentsPage({ role, loading = false }) {
  const { lang, docs, setDocs } = useApp();
  const t = copy[lang];
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState({ title: "", source: "", date: "", visibility: "" });
  const [file, setFile] = useState(null);
  const [pendingDelete, setPendingDelete] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const isAdmin = role === "admin";
  const visibleDocs = isAdmin ? docs.filter((doc) => !doc.is_mine) : role === "lecteur" ? docs.filter((doc) => doc.is_mine) : docs.filter((doc) => !doc.is_mine);
  const readyCount = visibleDocs.filter((doc) => doc.status === "ready").length;
  const processingCount = visibleDocs.filter((doc) => !["ready", "failed"].includes(doc.status)).length;
  const failedCount = visibleDocs.filter((doc) => doc.status === "failed").length;
  const update = (key) => (event) => setForm((value) => ({ ...value, [key]: event.target.value }));

  async function submitUpload(event) {
    event.preventDefault(); setError("");
    if (!file || !form.title.trim()) return setError(lang === "ar" ? "اختر ملفًا وأدخل عنوان الوثيقة." : "Choisissez un fichier et renseignez son titre.");
    if (file.size > 20_000_000) return setError(lang === "ar" ? "حجم الملف يتجاوز 20 ميغابايت." : "Le fichier dépasse la limite de 20 Mo.");
    if (role === "editeur" && !form.visibility) return setError(lang === "ar" ? "اختر مستوى الإتاحة." : "Choisissez une visibilité.");
    setBusy(true);
    try {
      const roles = role === "editeur" ? (form.visibility === "public" ? ["lecteur", "editeur"] : ["editeur"]) : [];
      const result = await api.documents.upload(file, { ...form, roles });
      const entry = { doc_id: result.doc_id, title: form.title, source_file: file.name, source: form.source, date: form.date, status: result.status, roles, is_mine: role !== "editeur" };
      setDocs((items) => [entry, ...items]);
      let current = result.status;
      while (!["ready", "failed"].includes(current)) {
        await pause(2000);
        const status = await api.documents.status(result.doc_id);
        current = status.status;
        setDocs((items) => items.map((item) => item.doc_id === result.doc_id ? { ...item, status: current, error: status.error, duplicate_of: status.duplicate_of } : item));
      }
      setForm({ title: "", source: "", date: "", visibility: "" }); setFile(null); setFormOpen(false);
    } catch (reason) { setError(reason.message || t.unavailable); }
    finally { setBusy(false); }
  }

  async function deleteDoc(docId) {
    try {
      await api.documents.remove(docId);
      setDocs((items) => items.filter((item) => item.doc_id !== docId));
    } catch (reason) { setError(reason.message); }
    finally { setPendingDelete(null); }
  }

  async function changeDocumentRoles(doc, visibility) {
    const roles = visibility === "public" ? ["lecteur", "editeur"] : ["editeur"];
    try {
      await api.admin.setDocumentRoles(doc.doc_id, roles);
      setDocs((items) => items.map((item) => item.doc_id === doc.doc_id ? { ...item, roles } : item));
    } catch (reason) { setError(reason.message); }
  }

  return <div className="mx-auto max-w-[1160px] px-4 py-8 md:px-8">
    <div className="flex flex-wrap items-end justify-between gap-5">
      <div><p className="text-[10px] font-bold uppercase tracking-[.14em] text-[#b76940]">DOCUMENTS · 02</p><h1 className={`mt-2 text-3xl font-semibold text-[#28362b] ${lang === "ar" ? "arabic" : ""}`}>{isAdmin ? t.docRights : t.docsTitle}</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-[#777b70]">{isAdmin ? t.adminDocsIntro : t.docsIntro}</p></div>
      {!isAdmin && <Button className="rounded-lg px-5 shadow-sm" onClick={() => setFormOpen(!formOpen)}><FilePlus2 size={17} />{t.upload}</Button>}
    </div>
    {!loading && <div className="mt-7 grid gap-px overflow-hidden rounded-xl border border-[#e3e3da] bg-[#e3e3da] sm:grid-cols-3">
      <Metric icon={FileText} label={t.documents} value={visibleDocs.length} />
      <Metric icon={CheckCircle2} label={t.readyDocs} value={readyCount} />
      <Metric icon={failedCount > 0 ? CircleAlert : Clock3} label={failedCount > 0 ? statusNames.failed[lang] : t.pending} value={failedCount || processingCount} />
    </div>}
    {formOpen && <form onSubmit={submitUpload} className="mt-7 grid gap-4 rounded-xl border border-[#dfe1d7] bg-[#fbfaf6] p-5 shadow-sm md:grid-cols-2 md:p-6 fade-in">
      <div className="md:col-span-2 flex items-center justify-between"><h2 className="font-bold text-[#30382e]">{t.upload}</h2><button type="button" aria-label="Fermer" onClick={() => setFormOpen(false)} className="focus-ring rounded p-1 text-[#777b70]"><X size={18} /></button></div>
      <Field label={t.title} required value={form.title} onChange={update("title")} /><Field label={t.source} value={form.source} onChange={update("source")} /><Field label={t.date} placeholder="2025-03-12" value={form.date} onChange={update("date")} />
      <label className="grid gap-1.5 text-sm font-semibold text-[#434a40]">{t.file}<span className="flex h-11 items-center gap-2 overflow-hidden rounded-md border border-[#dedfd5] bg-white px-3 text-sm font-normal text-[#777b70]"><Upload size={16} /><span className="truncate">{file?.name || t.chooseFile}</span><input type="file" accept={FILE_TYPES} required className="absolute h-px w-px opacity-0" onChange={(event) => setFile(event.target.files?.[0] || null)} /></span></label>
      {role === "editeur" ? <fieldset className="md:col-span-2"><legend className="mb-2 text-sm font-semibold text-[#434a40]">{t.visibility} <span className="text-[#a54132">*</span></legend><div className="flex flex-wrap gap-3">{["public", "internal"].map((visibility) => <label key={visibility} className={`flex cursor-pointer items-center gap-2 rounded-md border px-4 py-3 text-sm ${form.visibility === visibility ? "border-[#245c48] bg-[#edf2eb] text-[#245c48]" : "border-[#dedfd5] bg-white text-[#62685e]"}`}><input type="radio" name="visibility" value={visibility} checked={form.visibility === visibility} onChange={update("visibility")} className="accent-[#245c48]" />{t[visibility]}</label>)}</div></fieldset> : <div className="md:col-span-2 rounded-md border-s-2 border-[#789078] bg-[#edf2eb] px-4 py-3 text-sm text-[#4e6651]">{t.private}</div>}
      {error && <p role="alert" className="md:col-span-2 text-sm text-[#a54132]">{error}</p>}
      <div className="flex gap-2 md:col-span-2"><Button disabled={busy}>{busy ? <Activity size={16} className="animate-pulse" /> : <Upload size={16} />}{t.uploadAction}</Button><Button type="button" variant="outline" onClick={() => setFormOpen(false)}>{t.cancel}</Button></div>
    </form>}
    <section className="mt-8 overflow-hidden rounded-xl border border-[#e3e3da] bg-[#fbfaf6] shadow-sm">
      <div className="flex items-center justify-between gap-4 border-b border-[#e9e9e2] px-5 py-4"><h2 className="font-bold text-[#30382e]">{t.documents}</h2><span className="rounded-full bg-[#edf0e9] px-3 py-1 text-xs font-semibold text-[#526750]">{loading ? "…" : visibleDocs.length}</span></div>
      {visibleDocs.length > 0 && <div className="hidden grid-cols-[minmax(180px,1.5fr)_minmax(150px,1fr)_110px_100px_130px] gap-4 bg-[#f1f1eb] px-5 py-3 text-[10px] font-bold uppercase tracking-[.1em] text-[#767a70] lg:grid"><span>{t.title}</span><span>{t.originalName}</span><span>{t.status}</span><span>{t.access}</span><span>{t.actions}</span></div>}
      {loading ? <p role="status" className="px-5 py-12 text-center text-sm text-[#777b70]">{t.loadingData}</p> : visibleDocs.length === 0 ? <div className="grid min-h-64 justify-items-center content-center gap-3 px-5 py-12 text-center"><span className="grid h-14 w-14 place-items-center rounded-xl border border-[#dce4d9] bg-[#e9eee7] text-[#245c48]"><FileText size={23} /></span><h3 className="font-semibold text-[#30382e]">{t.noDocs}</h3><p className="max-w-md text-sm leading-6 text-[#777b70]">{isAdmin ? t.adminDocsIntro : t.docsIntro}</p></div> : visibleDocs.map((doc) => <div id={doc.doc_id} key={doc.doc_id} className="grid gap-3 border-t border-[#e9e9e2] bg-[#fbfaf6] px-5 py-4 transition-colors hover:bg-white lg:grid-cols-[minmax(180px,1.5fr)_minmax(150px,1fr)_110px_100px_130px] lg:items-center lg:gap-4">
        <div className="min-w-0"><span className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-[#85887d] lg:hidden">{t.title}</span><div dir="auto" className={`truncate text-sm font-bold text-[#31392f] ${lang === "ar" ? "text-right" : ""}`}>{doc.title}</div><div dir="auto" className="mt-1 truncate text-xs text-[#85887d]">{doc.source || "—"}{doc.date ? ` · ${doc.date}` : ""}</div></div>
        <div dir="auto" className="min-w-0"><span className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-[#85887d] lg:hidden">{t.originalName}</span><div className="truncate text-xs text-[#666c61] lg:text-sm">{doc.source_file}</div></div>
        <div><span className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-[#85887d] lg:hidden">{t.status}</span><StatusPill status={doc.status} lang={lang} />{doc.status === "failed" && <p className="mt-1 text-[11px] text-[#a54132]">{documentErrorMessage(doc.error, t)}</p>}</div>
        <div><span className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-[#85887d] lg:hidden">{t.access}</span><div className="text-xs text-[#656b61]">{doc.is_mine ? t.private : doc.roles?.includes("lecteur") ? t.public : t.internal}</div></div>
        <div className="flex flex-wrap items-center gap-2"><span className="me-auto text-[10px] font-semibold uppercase tracking-wide text-[#85887d] lg:hidden">{t.actions}</span>{isAdmin && !doc.is_mine && <select aria-label={t.access} value={doc.roles?.includes("lecteur") ? "public" : "internal"} onChange={(event) => changeDocumentRoles(doc, event.target.value)} className="focus-ring h-9 min-w-0 rounded border border-[#dedfd5] bg-white px-2 text-xs"><option value="public">{t.public}</option><option value="internal">{t.internal}</option></select>}
          {pendingDelete === doc.doc_id ? <div className="flex items-center gap-1"><Button variant="danger" className="h-8 min-h-8 max-w-full px-2 text-xs leading-tight" onClick={() => deleteDoc(doc.doc_id)}>{t.confirm}</Button><button onClick={() => setPendingDelete(null)} aria-label={t.cancel} className="focus-ring rounded p-1 text-[#777b70]"><X size={16} /></button></div> : <button onClick={() => setPendingDelete(doc.doc_id)} aria-label={t.delete} title={t.delete} className="focus-ring inline-flex min-h-10 items-center gap-2 rounded-md border border-[#e7c9c2] bg-[#fffaf8] px-3 text-xs font-semibold text-[#a54132] transition-colors hover:bg-[#f7e9e5]"><Trash2 size={15} /><span>{t.delete}</span></button>}</div>
        {doc.duplicate_of?.length > 0 && <div className="text-xs text-[#926a38] md:col-span-5">{t.duplicate} {doc.duplicate_of.map((id) => <a key={id} className="ms-2 underline" href={`#${id}`}>{id}</a>)}</div>}
      </div>)}
    </section>{error && !formOpen && <p role="alert" className="mt-4 text-sm text-[#a54132]">{error}</p>}
  </div>;
}