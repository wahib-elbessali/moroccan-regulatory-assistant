import { useState } from "react";
import { Activity, FilePlus2, FileText, Trash2, Upload, X } from "lucide-react";
import { api } from "../../api.js";
import { useApp } from "../../app/AppContext.jsx";
import { copy, FILE_TYPES, pause } from "../../app/data.js";
import { Button, Field, StatusPill } from "../../components/Ui.jsx";

export default function DocumentsPage({ role }) {
  const { lang, docs, setDocs, demo } = useApp();
  const t = copy[lang];
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState({ title: "", source: "", date: "", visibility: "" });
  const [file, setFile] = useState(null);
  const [pendingDelete, setPendingDelete] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const isAdmin = role === "admin";
  const visibleDocs = isAdmin ? docs.filter((doc) => !doc.is_mine && doc.owner_id == null) : role === "lecteur" ? docs.filter((doc) => doc.is_mine) : docs.filter((doc) => !doc.is_mine);
  const update = (key) => (event) => setForm((value) => ({ ...value, [key]: event.target.value }));

  async function submitUpload(event) {
    event.preventDefault(); setError("");
    if (!file || !form.title.trim()) return setError(lang === "ar" ? "اختر ملفًا وأدخل عنوان الوثيقة." : "Choisissez un fichier et renseignez son titre.");
    if (file.size > 20_000_000) return setError(lang === "ar" ? "حجم الملف يتجاوز 20 ميغابايت." : "Le fichier dépasse la limite de 20 Mo.");
    if (role === "editeur" && !form.visibility) return setError(lang === "ar" ? "اختر مستوى الإتاحة." : "Choisissez une visibilité.");
    setBusy(true);
    try {
      const roles = role === "editeur" ? (form.visibility === "public" ? ["lecteur", "editeur"] : ["editeur"]) : [];
      if (demo) {
        const entry = { doc_id: crypto.randomUUID(), title: form.title, source_file: file.name, source: form.source, date: form.date, status: "received", roles, is_mine: role !== "editeur", owner_id: role === "editeur" ? null : "demo-user" };
        setDocs((items) => [entry, ...items]);
        for (const status of ["extracting", "chunked", "indexed", "ready"]) {
          await pause(500);
          setDocs((items) => items.map((item) => item.doc_id === entry.doc_id ? { ...item, status } : item));
        }
      } else {
        const result = await api.documents.upload(file, { ...form, roles });
        const entry = { doc_id: result.doc_id, title: form.title, source_file: file.name, source: form.source, date: form.date, status: result.status, roles, is_mine: role !== "editeur", owner_id: role === "editeur" ? null : "mine" };
        setDocs((items) => [entry, ...items]);
        let current = result.status;
        while (!["ready", "failed"].includes(current)) {
          await pause(2000);
          const status = await api.documents.status(result.doc_id);
          current = status.status;
          setDocs((items) => items.map((item) => item.doc_id === result.doc_id ? { ...item, status: current, error: status.error, duplicate_of: status.duplicate_of } : item));
        }
      }
      setForm({ title: "", source: "", date: "", visibility: "" }); setFile(null); setFormOpen(false);
    } catch (reason) { setError(reason.message || t.unavailable); }
    finally { setBusy(false); }
  }

  async function deleteDoc(docId) {
    try {
      if (!demo) await api.documents.remove(docId);
      setDocs((items) => items.filter((item) => item.doc_id !== docId));
    } catch (reason) { setError(reason.message); }
    finally { setPendingDelete(null); }
  }

  async function changeDocumentRoles(doc, visibility) {
    const roles = visibility === "public" ? ["lecteur", "editeur"] : ["editeur"];
    try {
      if (!demo) await api.admin.setDocumentRoles(doc.doc_id, roles);
      setDocs((items) => items.map((item) => item.doc_id === doc.doc_id ? { ...item, roles } : item));
    } catch (reason) { setError(reason.message); }
  }

  return <div className="mx-auto max-w-[1160px] px-4 py-8 md:px-8">
    <div className="flex flex-wrap items-end justify-between gap-4"><div><p className="text-[10px] font-bold uppercase tracking-[.14em] text-[#b76940]">DOCUMENTS · 02</p><h1 className={`mt-2 text-3xl font-semibold text-[#28362b] ${lang === "ar" ? "arabic" : ""}`}>{isAdmin ? t.docRights : t.docsTitle}</h1><p className="mt-2 text-sm text-[#777b70]">{t.docsIntro}</p></div>{!isAdmin && <Button onClick={() => setFormOpen(!formOpen)}><FilePlus2 size={17} />{t.upload}</Button>}</div>
    {formOpen && <form onSubmit={submitUpload} className="mt-7 grid gap-4 border-y border-[#dfe1d7] bg-[#fbfaf6] p-5 md:grid-cols-2 md:p-6 fade-in">
      <div className="md:col-span-2 flex items-center justify-between"><h2 className="font-bold text-[#30382e]">{t.upload}</h2><button type="button" aria-label="Fermer" onClick={() => setFormOpen(false)} className="focus-ring rounded p-1 text-[#777b70]"><X size={18} /></button></div>
      <Field label={t.title} required value={form.title} onChange={update("title")} /><Field label={t.source} value={form.source} onChange={update("source")} /><Field label={t.date} placeholder="2025-03-12" value={form.date} onChange={update("date")} />
      <label className="grid gap-1.5 text-sm font-semibold text-[#434a40]">{t.file}<span className="flex h-11 items-center gap-2 overflow-hidden rounded-md border border-[#dedfd5] bg-white px-3 text-sm font-normal text-[#777b70]"><Upload size={16} /><span className="truncate">{file?.name || t.chooseFile}</span><input type="file" accept={FILE_TYPES} required className="absolute h-px w-px opacity-0" onChange={(event) => setFile(event.target.files?.[0] || null)} /></span></label>
      {role === "editeur" ? <fieldset className="md:col-span-2"><legend className="mb-2 text-sm font-semibold text-[#434a40]">{t.visibility} <span className="text-[#a54132">*</span></legend><div className="flex flex-wrap gap-3">{["public", "internal"].map((visibility) => <label key={visibility} className={`flex cursor-pointer items-center gap-2 rounded-md border px-4 py-3 text-sm ${form.visibility === visibility ? "border-[#245c48] bg-[#edf2eb] text-[#245c48]" : "border-[#dedfd5] bg-white text-[#62685e]"}`}><input type="radio" name="visibility" value={visibility} checked={form.visibility === visibility} onChange={update("visibility")} className="accent-[#245c48]" />{t[visibility]}</label>)}</div></fieldset> : <div className="md:col-span-2 rounded-md border-s-2 border-[#789078] bg-[#edf2eb] px-4 py-3 text-sm text-[#4e6651]">{t.private}</div>}
      {error && <p role="alert" className="md:col-span-2 text-sm text-[#a54132]">{error}</p>}
      <div className="flex gap-2 md:col-span-2"><Button disabled={busy}>{busy ? <Activity size={16} className="animate-pulse" /> : <Upload size={16} />}{t.uploadAction}</Button><Button type="button" variant="outline" onClick={() => setFormOpen(false)}>{t.cancel}</Button></div>
    </form>}
    <div className="mt-8 overflow-hidden border-y border-[#e3e3da]"><div className="hidden grid-cols-[minmax(220px,1.5fr)_minmax(180px,1fr)_130px_120px_100px] gap-4 bg-[#efefe8] px-4 py-3 text-[10px] font-bold uppercase tracking-[.1em] text-[#767a70] md:grid"><span>{t.title}</span><span>{t.originalName}</span><span>{t.status}</span><span>{t.access}</span><span>{t.actions}</span></div>
      {visibleDocs.length === 0 ? <div className="grid justify-items-center gap-3 py-16 text-center"><span className="grid h-12 w-12 place-items-center rounded-md bg-[#edeee8] text-[#8b9085]"><FileText size={22} /></span><p className="text-sm text-[#777b70]">{t.noDocs}</p></div> : visibleDocs.map((doc) => <div id={doc.doc_id} key={doc.doc_id} className="grid gap-3 border-t border-[#e9e9e2] bg-[#fbfaf6] px-4 py-4 md:grid-cols-[minmax(220px,1.5fr)_minmax(180px,1fr)_130px_120px_100px] md:items-center md:gap-4">
        <div className="min-w-0"><div dir="auto" className="truncate text-sm font-bold text-[#31392f]">{doc.title}</div><div dir="auto" className="mt-1 truncate text-xs text-[#85887d]">{doc.source || "—"}{doc.date ? ` · ${doc.date}` : ""}</div></div><div dir="auto" className="truncate text-xs text-[#666c61] md:text-sm">{doc.source_file}</div><div><StatusPill status={doc.status} lang={lang} />{doc.status === "failed" && <p className="mt-1 text-[11px] text-[#a54132]">{doc.error || t.failedHint}</p>}</div>
        <div className="text-xs text-[#656b61]">{doc.owner_id || doc.is_mine ? t.private : doc.roles?.includes("lecteur") ? t.public : t.internal}</div>
        <div className="flex items-center gap-2">{isAdmin && !doc.is_mine && <select aria-label={t.access} value={doc.roles?.includes("lecteur") ? "public" : "internal"} onChange={(event) => changeDocumentRoles(doc, event.target.value)} className="focus-ring h-9 min-w-0 rounded border border-[#dedfd5] bg-white px-2 text-xs"><option value="public">{t.public}</option><option value="internal">{t.internal}</option></select>}
          {pendingDelete === doc.doc_id ? <div className="flex items-center gap-1"><Button variant="danger" className="h-8 min-h-8 px-2 text-xs" onClick={() => deleteDoc(doc.doc_id)}>{t.confirm}</Button><button onClick={() => setPendingDelete(null)} aria-label={t.cancel} className="focus-ring rounded p-1 text-[#777b70]"><X size={16} /></button></div> : <button onClick={() => setPendingDelete(doc.doc_id)} aria-label={t.delete} title={t.delete} className="focus-ring rounded-md p-2 text-[#8b6659] hover:bg-[#f7e9e5]"><Trash2 size={16} /></button>}</div>
        {doc.duplicate_of?.length > 0 && <div className="text-xs text-[#926a38] md:col-span-5">{t.duplicate} {doc.duplicate_of.map((id) => <a key={id} className="ms-2 underline" href={`#${id}`}>{id}</a>)}</div>}
      </div>)}
    </div>{error && !formOpen && <p role="alert" className="mt-4 text-sm text-[#a54132]">{error}</p>}
  </div>;
}