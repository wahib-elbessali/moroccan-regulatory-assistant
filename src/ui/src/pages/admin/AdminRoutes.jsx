import { createContext, useContext, useEffect, useState } from "react";
import { Activity, Check, Clock3, FileCheck2, Plus, Users, X } from "lucide-react";
import { Link, Outlet } from "react-router-dom";
import { api } from "../../api.js";
import { useApp } from "../../app/AppContext.jsx";
import { copy, initialRequests, initialUsers, roleLabel } from "../../app/data.js";
import { Button, Field, Metric, PageHeading } from "../../components/Ui.jsx";

const AdminContext = createContext(null);
const mockRoles = [{ role_id: 1, name: "admin", web_enabled: true }, { role_id: 2, name: "editeur", web_enabled: true }, { role_id: 3, name: "lecteur", web_enabled: true }];
const mockAudit = [{ id: 1, action: "DOCUMENT_UPLOAD", timestamp: "2026-11-11T09:42:00Z", user: "mehdi.juriste", details: "doc-public-12" }, { id: 2, action: "LOGIN", timestamp: "2026-11-11T09:38:00Z", user: "amina.admin", details: "success: true" }];

export function AdminDataProvider() {
  const { demo, docs, setDocs, setError } = useApp();
  const [users, setUsers] = useState(initialUsers);
  const [requests, setRequests] = useState(initialRequests);
  const [roles, setRoles] = useState(mockRoles);
  const [audit, setAudit] = useState(mockAudit);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (demo || loaded) return;
    let active = true;
    setLoading(true);
    Promise.all([api.admin.users(), api.admin.roles(), api.admin.accountRequests(), api.admin.audit(), api.documents.list()])
      .then(([userData, roleData, requestData, auditData, documentData]) => {
        if (!active) return;
        setUsers(userData); setRoles(roleData); setRequests(requestData); setAudit(auditData); setDocs(documentData); setLoaded(true);
      })
      .catch((reason) => setError(reason.message))
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [demo, loaded, setDocs, setError]);

  const value = { demo, docs, users, setUsers, requests, setRequests, roles, setRoles, audit, loading, setError };
  return <AdminContext.Provider value={value}><Outlet /></AdminContext.Provider>;
}

function useAdmin() {
  const value = useContext(AdminContext);
  if (!value) throw new Error("Admin pages must be inside AdminDataProvider");
  return value;
}

export function AdminOverviewPage() {
  const { docs, users, requests, audit, loading } = useAdmin();
  const { lang } = useApp();
  const t = copy[lang];
  return <div className="mx-auto max-w-[1160px] px-4 py-8 md:px-8"><PageHeading eyebrow="ADMINISTRATION · 03" title={t.adminTitle} intro={t.adminIntro} />
    <div className="mt-8 grid gap-px border border-[#e3e3da] bg-[#e3e3da] sm:grid-cols-3"><Metric icon={FileCheck2} label={t.totalDocs} value={docs.length} /><Metric icon={Clock3} label={t.pending} value={docs.filter((doc) => !["ready", "failed"].includes(doc.status)).length} /><Metric icon={Users} label={t.accountCount} value={users.length} /></div>
    <div className="mt-8 grid gap-8 md:grid-cols-[1.2fr_.8fr]"><section><div className="mb-3 flex items-center justify-between"><h2 className="font-bold text-[#343b32]">{t.requests}</h2><Link to="/admin/requests" className="focus-ring rounded px-2 py-1 text-sm font-semibold text-[#245c48]">{t.requests} →</Link></div>{requests.slice(0, 3).map((request) => <div key={request.request_id} className="flex items-center justify-between border-t border-[#e3e3da] py-3"><div><div className="text-sm font-semibold text-[#3d443a]">{request.full_name}</div><div className="text-xs text-[#81857a]">@{request.username}</div></div><span className="rounded bg-[#f3eddf] px-2 py-1 text-[10px] font-semibold text-[#896a34]">{lang === "ar" ? "معلق" : "En attente"}</span></div>)}{requests.length === 0 && <p className="border-t border-[#e3e3da] py-4 text-sm text-[#777b70]">{t.noRequests}</p>}</section>
      <section><h2 className="mb-3 font-bold text-[#343b32]">{t.recentActivity}</h2>{audit.slice(0, 3).map((event) => <div key={event.id || event.request_id} className="flex gap-3 border-t border-[#e3e3da] py-3"><span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-[#b76940]" /><div><div className="text-xs font-semibold text-[#454b42]">{event.action}</div><div className="mt-1 text-[11px] text-[#81857a]">{event.username || event.user || "—"} · {event.timestamp ? new Date(event.timestamp).toLocaleTimeString(lang === "ar" ? "ar-MA" : "fr-FR", { hour: "2-digit", minute: "2-digit" }) : t.justNow}</div></div></div>)}</section></div>
    {loading && <Activity className="mt-4 animate-pulse text-[#789078]" size={17} />}
  </div>;
}

export function AdminUsersPage() {
  const { lang } = useApp();
  const { demo, users, setUsers, roles, setError } = useAdmin();
  const t = copy[lang];
  const [createOpen, setCreateOpen] = useState(false);
  const [newUser, setNewUser] = useState({ username: "", full_name: "", password: "", role_id: "" });

  async function addUser(event) {
    event.preventDefault();
    try {
      const role = roles.find((item) => item.role_id === Number(newUser.role_id));
      if (!role) return setError(lang === "ar" ? "اختر دورًا." : "Choisissez un rôle.");
      if (!demo) await api.admin.createUser({ ...newUser, role_id: Number(newUser.role_id) });
      setUsers((items) => [...items, { user_id: crypto.randomUUID(), ...newUser, role: role.name, is_active: true }]);
      setCreateOpen(false); setNewUser({ username: "", full_name: "", password: "", role_id: "" });
    } catch (reason) { setError(reason.message); }
  }

  async function updateUser(user, fields) {
    try {
      if (!demo) {
        if (fields.role) await api.admin.updateUserRole(user.user_id, roles.find((item) => item.name === fields.role)?.role_id);
        if (fields.is_active !== undefined) await api.admin.setUserActive(user.user_id, fields.is_active);
      }
      setUsers((items) => items.map((item) => item.user_id === user.user_id ? { ...item, ...fields } : item));
    } catch (reason) { setError(reason.message); }
  }

  return <div className="mx-auto max-w-[1160px] px-4 py-8 md:px-8"><PageHeading eyebrow="IDENTITY · 03" title={t.users} intro={t.adminIntro} /><div className="mt-7 flex justify-end"><Button onClick={() => setCreateOpen(!createOpen)}><Plus size={16} />{t.addUser}</Button></div>
    {createOpen && <form onSubmit={addUser} className="mt-4 grid gap-3 border-y border-[#dfe1d7] bg-[#fbfaf6] p-5 md:grid-cols-2"><Field label={t.username} required value={newUser.username} onChange={(event) => setNewUser({ ...newUser, username: event.target.value })} /><Field label={t.fullName} required value={newUser.full_name} onChange={(event) => setNewUser({ ...newUser, full_name: event.target.value })} /><Field label={t.password} type="password" required minLength={8} value={newUser.password} onChange={(event) => setNewUser({ ...newUser, password: event.target.value })} /><label className="grid gap-1.5 text-sm font-semibold">{t.role}<select required value={newUser.role_id} onChange={(event) => setNewUser({ ...newUser, role_id: event.target.value })} className="focus-ring h-11 rounded-md border border-[#dedfd5] bg-white px-3"><option value="">{t.chooseRole}</option>{roles.map((item) => <option key={item.role_id} value={item.role_id}>{roleLabel(item.name, t)}</option>)}</select></label><div className="flex gap-2 md:col-span-2"><Button>{t.createUser}</Button><Button type="button" variant="outline" onClick={() => setCreateOpen(false)}>{t.cancel}</Button></div></form>}
    <div className="mt-6 overflow-hidden border-y border-[#e3e3da]">{users.map((user) => <div key={user.user_id} className="grid gap-3 border-b border-[#e9e9e2] bg-[#fbfaf6] p-4 md:grid-cols-[1.5fr_1fr_150px_120px] md:items-center"><div><div dir="auto" className="font-semibold text-[#31392f]">{user.full_name}</div><div className="text-xs text-[#81857a]">@{user.username}</div></div><select aria-label={t.role} value={user.role} onChange={(event) => updateUser(user, { role: event.target.value })} className="focus-ring h-9 max-w-48 rounded border border-[#dedfd5] bg-white px-2 text-sm">{roles.map((item) => <option key={item.role_id} value={item.name}>{roleLabel(item.name, t)}</option>)}</select><span className={`text-xs font-semibold ${user.is_active ? "text-[#527c56]" : "text-[#a54132]"}`}>{user.is_active ? t.active : t.disabled}</span><button onClick={() => updateUser(user, { is_active: !user.is_active })} className="focus-ring justify-self-start rounded border border-[#dedfd5] bg-white px-3 py-2 text-xs font-semibold text-[#4c554a]">{user.is_active ? t.disabled : t.active}</button></div>)}</div>
  </div>;
}

export function AdminRequestsPage() {
  const { lang } = useApp();
  const { demo, requests, setRequests, setUsers, roles, setError } = useAdmin();
  const t = copy[lang];
  const [selectedRoles, setSelectedRoles] = useState({});
  const [confirmRequest, setConfirmRequest] = useState(null);

  async function decide(request, decision) {
    const roleName = selectedRoles[request.request_id];
    if (decision === "approve" && !roleName) return setError(lang === "ar" ? "اختر دورًا قبل الموافقة." : "Choisissez un rôle avant d’approuver.");
    const role = roles.find((item) => item.name === roleName);
    try {
      if (!demo) await api.admin.decideAccountRequest(request.request_id, decision, role?.role_id);
      if (decision === "approve") setUsers((items) => [...items, { user_id: crypto.randomUUID(), username: request.username, full_name: request.full_name, role: roleName, is_active: true }]);
      setRequests((items) => items.filter((item) => item.request_id !== request.request_id)); setConfirmRequest(null);
    } catch (reason) { setError(reason.message); }
  }

  return <div className="mx-auto max-w-[1160px] px-4 py-8 md:px-8"><PageHeading eyebrow="ACCOUNT REQUESTS · 03" title={t.requests} intro={t.adminIntro} /><div className="mt-7 overflow-hidden border-y border-[#e3e3da]">{requests.length === 0 ? <p className="py-16 text-center text-sm text-[#777b70]">{t.noRequests}</p> : requests.map((request) => <div key={request.request_id} className="grid gap-4 border-b border-[#e9e9e2] bg-[#fbfaf6] p-4 md:grid-cols-[1.3fr_1fr_180px_auto] md:items-center"><div><div dir="auto" className="font-semibold text-[#31392f]">{request.full_name}</div><div className="text-xs text-[#81857a]">@{request.username}</div></div><span className="text-xs text-[#777b70]">{new Date(request.created_at).toLocaleString(lang === "ar" ? "ar-MA" : "fr-FR")}</span><select aria-label={t.chooseRole} value={selectedRoles[request.request_id] || ""} onChange={(event) => setSelectedRoles((items) => ({ ...items, [request.request_id]: event.target.value }))} className="focus-ring h-10 rounded border border-[#dedfd5] bg-white px-2 text-sm"><option value="">{t.chooseRole}</option>{roles.map((item) => <option key={item.role_id} value={item.name}>{roleLabel(item.name, t)}</option>)}</select><div className="flex gap-2">{confirmRequest === request.request_id ? <><Button className="h-9 min-h-9 px-3 text-xs" onClick={() => decide(request, "approve")}>{t.confirm}</Button><Button variant="outline" className="h-9 min-h-9 px-3 text-xs" onClick={() => decide(request, "reject")}>{t.reject}</Button><button aria-label={t.cancel} onClick={() => setConfirmRequest(null)} className="focus-ring rounded p-1"><X size={16} /></button></> : <><Button className="h-9 min-h-9 px-3 text-xs" onClick={() => setConfirmRequest(request.request_id)}><Check size={14} />{t.approve}</Button><Button variant="outline" className="h-9 min-h-9 px-3 text-xs" onClick={() => setConfirmRequest(request.request_id)}>{t.reject}</Button></>}</div></div>)}</div></div>;
}

export function AdminWebPage() {
  const { lang } = useApp();
  const { demo, roles, setRoles, setError } = useAdmin();
  const t = copy[lang];
  async function setWeb(role) {
    try {
      if (!demo) await api.admin.setRoleWeb(role.role_id, !role.web_enabled);
      setRoles((items) => items.map((item) => item.role_id === role.role_id ? { ...item, web_enabled: !item.web_enabled } : item));
    } catch (reason) { setError(reason.message); }
  }
  return <div className="mx-auto max-w-[900px] px-4 py-8 md:px-8"><PageHeading eyebrow="WEB ACCESS · 03" title={t.roleWeb} intro={lang === "ar" ? "تُطبّق التغييرات على الطلبات الجديدة مباشرةً." : "Les changements s’appliquent aux prochaines requêtes."} /><div className="mt-8 border-y border-[#e3e3da]">{roles.map((role) => <label key={role.role_id} className="flex cursor-pointer items-center justify-between gap-4 border-b border-[#e9e9e2] bg-[#fbfaf6] px-4 py-5"><span><span className="block font-semibold text-[#31392f]">{roleLabel(role.name, t)}</span><span className="mt-1 block text-xs text-[#81857a]">{t.allowWeb}</span></span><input type="checkbox" checked={role.web_enabled} onChange={() => setWeb(role)} className="h-5 w-5 accent-[#245c48]" /></label>)}</div></div>;
}

export function AdminAuditPage() {
  const { lang } = useApp();
  const { audit } = useAdmin();
  const t = copy[lang];
  return <div className="mx-auto max-w-[1160px] px-4 py-8 md:px-8"><PageHeading eyebrow="AUDIT TRAIL · 03" title={t.audit} intro={t.adminIntro} /><div className="mt-8 overflow-hidden border-y border-[#e3e3da]">{audit.length === 0 ? <p className="py-16 text-center text-sm text-[#777b70]">{t.auditEmpty}</p> : audit.map((event) => <div key={event.id || event.request_id} className="grid gap-2 border-b border-[#e9e9e2] bg-[#fbfaf6] px-4 py-4 md:grid-cols-[190px_180px_1fr_1fr] md:items-center"><span className="text-xs text-[#81857a]">{event.timestamp ? new Date(event.timestamp).toLocaleString(lang === "ar" ? "ar-MA" : "fr-FR") : "—"}</span><span className="inline-flex w-fit rounded bg-[#edf0e9] px-2 py-1 text-[10px] font-bold tracking-wide text-[#526750]">{event.action}</span><span className="text-sm text-[#424940]">{event.username || event.user || event.user_id || "—"}</span><span className="break-all text-xs text-[#777b70]">{typeof event.details === "string" ? event.details : JSON.stringify(event.details || {})}</span></div>)}</div></div>;
}