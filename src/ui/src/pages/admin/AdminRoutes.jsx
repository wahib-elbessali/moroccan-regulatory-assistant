import { createContext, useContext, useEffect, useState } from "react";
import { Activity, Check, Clock3, FileCheck2, Plus, Users, X } from "lucide-react";
import { Link, Outlet } from "react-router-dom";
import { api } from "../../api.js";
import { useApp } from "../../app/AppContext.jsx";
import { MIN_PASSWORD, copy, roleLabel } from "../../app/data.js";
import { Button, Field, Metric, PageHeading } from "../../components/Ui.jsx";
import DocumentsPage from "../documents/DocumentsPage.jsx";

const AdminContext = createContext(null);

function isUserResponse(value) {
  return value && typeof value.user_id === "string" && typeof value.username === "string"
    && typeof value.full_name === "string" && typeof value.role === "string"
    && typeof value.is_active === "boolean" && typeof value.created_at === "string";
}

function isRoleResponse(value) {
  return value && Number.isInteger(value.role_id) && typeof value.name === "string"
    && typeof value.web_enabled === "boolean";
}

function isAccountRequestResponse(value) {
  return value && typeof value.request_id === "string" && typeof value.username === "string"
    && typeof value.full_name === "string" && ["pending", "approved", "rejected"].includes(value.status)
    && typeof value.created_at === "string";
}

function isDocumentResponse(value) {
  return value && typeof value.doc_id === "string" && typeof value.title === "string"
    && typeof value.source_file === "string" && typeof value.status === "string"
    && Array.isArray(value.roles) && typeof value.is_mine === "boolean"
    && typeof value.created_at === "string";
}

function isAuditLogResponse(value) {
  return value && typeof value === "object" && !Array.isArray(value);
}

function requireApiList(value, predicate, endpoint, lang) {
  if (!Array.isArray(value) || value.some((item) => !predicate(item))) {
    throw new Error(copy[lang].invalidApiResponse.replace("{endpoint}", endpoint));
  }
  return value;
}

function requireApiObject(value, predicate, endpoint, lang) {
  if (!predicate(value)) throw new Error(copy[lang].invalidApiResponse.replace("{endpoint}", endpoint));
  return value;
}
function auditActionLabel(action, t) {
  if (typeof action !== "string" || !action) return t.audit;
  return t.auditActions[action] || action.replaceAll("_", " ");
}

function auditActorLabel(event, users, t) {
  if (!event.user_id) return t.auditAnonymousActor;
  const user = users.find((item) => item.user_id === event.user_id);
  if (!user) return t.auditUnknownActor;
  const name = user.role === "admin" ? roleLabel("admin", t) : user.full_name;
  return `${name} (@${user.username})`;
}

function auditFieldLabel(field, t) {
  return t.auditFields[field] || field.replaceAll("_", " ");
}

function shortAuditReference(value, t) {
  const text = String(value);
  return text.length > 16 ? `${t.auditReference} ${text.slice(0, 8)}…${text.slice(-4)}` : text;
}

function auditValue(field, value, users, docs, t) {
  if (value === null || value === undefined) return "—";
  if (field === "roles" && Array.isArray(value)) return value.map((role) => roleLabel(String(role), t)).join(", ");
  if (field === "role" || field === "new_role") return roleLabel(String(value), t);
  if (["target_user_id", "approved_user", "created_user_id"].includes(field)) {
    const user = users.find((item) => item.user_id === value);
    if (user) return `${user.full_name} (@${user.username})`;
  }
  if (field === "doc_id") {
    const document = docs.find((item) => item.doc_id === value);
    if (document) return document.title;
  }
  if (typeof value === "boolean") {
    if (field === "success") return value ? t.auditSuccess : t.auditFailure;
    if (field === "failed") return value ? t.auditFailure : t.auditSuccess;
    if (field === "rejected") return value ? t.auditRejected : t.auditApproved;
    if (field === "is_active") return value ? t.active : t.disabled;
    return value ? t.auditYes : t.auditNo;
  }
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  if (typeof value === "string" && (field.endsWith("_id") || field.endsWith("_user"))) {
    return shortAuditReference(value, t);
  }
  return String(value);
}

export function AdminDataProvider() {
  const { lang, docs, setDocs, setError } = useApp();
  const [users, setUsers] = useState([]);
  const [requests, setRequests] = useState([]);
  const [roles, setRoles] = useState([]);
  const [audit, setAudit] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (loaded) return;
    let active = true;
    setLoading(true);
    Promise.all([api.admin.users(), api.admin.roles(), api.admin.accountRequests(), api.admin.audit(), api.documents.list()])
      .then(([userData, roleData, requestData, auditData, documentData]) => {
        if (!active) return;
        setUsers(requireApiList(userData, isUserResponse, "/admin/users", lang));
        setRoles(requireApiList(roleData, isRoleResponse, "/admin/roles", lang));
        setRequests(requireApiList(requestData, isAccountRequestResponse, "/admin/account-requests", lang)
          .filter((request) => request.status === "pending"));
        setAudit(requireApiList(auditData, isAuditLogResponse, "/admin/audit", lang));
        setDocs(requireApiList(documentData, isDocumentResponse, "/documents", lang));
        setLoaded(true);
      })
      .catch((reason) => setError(reason.message))
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [lang, loaded, setDocs, setError]);

  const value = { docs, users, setUsers, requests, setRequests, roles, setRoles, audit, loading, setError };
  return <AdminContext.Provider value={value}>
    <Outlet />
  </AdminContext.Provider>;
}

function useAdmin() {
  const value = useContext(AdminContext);
  if (!value) throw new Error("Admin pages must be inside AdminDataProvider");
  return value;
}

export function AdminDocumentsPage() {
  const { loading } = useAdmin();
  return <DocumentsPage role="admin" loading={loading} />;
}

export function AdminOverviewPage() {
  const { docs, users, requests, audit, loading } = useAdmin();
  const { lang } = useApp();
  const t = copy[lang];
  const corpusDocs = docs.filter((doc) => !doc.is_mine);
  return <div className="mx-auto max-w-[1160px] px-4 py-8 md:px-8">
    <PageHeading eyebrow={`${t.eyebrowAdmin} · 03`} title={t.adminTitle} intro={t.adminIntro} />
    {loading ? <div role="status" className="mt-8 rounded-xl border border-[#e3e3da] bg-[#fbfaf6] p-6 text-sm text-[#777b70]"><Activity className="me-2 inline animate-pulse text-[#789078]" size={17} />{t.loadingData}</div> : <>
      <div className="mt-8 grid gap-px overflow-hidden rounded-xl border border-[#e3e3da] bg-[#e3e3da] sm:grid-cols-3"><Metric icon={FileCheck2} label={t.totalDocs} value={corpusDocs.length} /><Metric icon={Clock3} label={t.pending} value={corpusDocs.filter((doc) => !["ready", "failed"].includes(doc.status)).length} /><Metric icon={Users} label={t.accountCount} value={users.length} /></div>
      <div className="mt-8 grid gap-5 md:grid-cols-[1.2fr_.8fr]">
        <section className="overflow-hidden rounded-xl border border-[#e3e3da] bg-[#fbfaf6] p-5">
          <div className="mb-3 flex items-center justify-between gap-3"><div><h2 className="font-bold text-[#343b32]">{t.requests}</h2><p className="mt-1 text-xs text-[#81857a]">{t.requestsIntro}</p></div><Link to="/admin/requests" className="focus-ring shrink-0 rounded px-2 py-1 text-sm font-semibold text-[#245c48]">{t.requests} {lang === "ar" ? "←" : "→"}</Link></div>
          {requests.length === 0 ? <p className="border-t border-[#e3e3da] py-4 text-sm text-[#777b70]">{t.noRequests}</p> : requests.slice(0, 3).map((request) => <div key={request.request_id} className="flex items-center justify-between gap-4 border-t border-[#e3e3da] py-3"><div><div className="text-sm font-semibold text-[#3d443a]">{request.full_name}</div><div className="text-xs text-[#81857a]">@{request.username}</div></div><span className="rounded-full bg-[#f3eddf] px-2.5 py-1 text-[10px] font-semibold text-[#896a34]">{t.pendingStatus}</span></div>)}
        </section>
        <section className="overflow-hidden rounded-xl border border-[#e3e3da] bg-[#fbfaf6] p-5">
          <h2 className="font-bold text-[#343b32]">{t.recentActivity}</h2><p className="mt-1 text-xs text-[#81857a]">{t.auditIntro}</p>
          {audit.length === 0 ? <p className="mt-3 border-t border-[#e3e3da] py-4 text-sm text-[#777b70]">{t.auditEmpty}</p> : audit.slice(0, 3).map((event, index) => <div key={`${event.timestamp || "event"}-${index}`} className="flex gap-3 border-t border-[#e3e3da] py-3"><span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-[#b76940]" /><div><div className="text-xs font-semibold text-[#454b42]">{auditActionLabel(event.action, t)}</div><div className="mt-1 text-[11px] text-[#81857a]">{auditActorLabel(event, users, t)}{event.timestamp && ` · ${new Date(event.timestamp).toLocaleTimeString(lang === "ar" ? "ar-MA" : "fr-FR", { hour: "2-digit", minute: "2-digit" })}`}</div></div></div>)}
        </section>
      </div>
    </>}
  </div>;
}

export function AdminUsersPage() {
  const { lang } = useApp();
  const { users, setUsers, roles, loading, setError } = useAdmin();
  const t = copy[lang];
  const [createOpen, setCreateOpen] = useState(false);
  const [newUser, setNewUser] = useState({ username: "", full_name: "", password: "", role_id: "" });

  async function addUser(event) {
    event.preventDefault();
    try {
      const role = roles.find((item) => item.role_id === Number(newUser.role_id));
      if (!role) throw new Error(t.noRoles);
      const createdUser = requireApiObject(
        await api.admin.createUser({ ...newUser, role_id: role.role_id }),
        isUserResponse,
        "POST /admin/users",
        lang,
      );
      setUsers((items) => [...items, createdUser]);
      setCreateOpen(false); setNewUser({ username: "", full_name: "", password: "", role_id: "" });
    } catch (reason) { setError(reason.message); }
  }

  async function updateUser(user, fields) {
    try {
      let updatedUser;
      if (fields.role) {
        const role = roles.find((item) => item.name === fields.role);
        if (!role) throw new Error(t.noRoles);
        updatedUser = requireApiObject(
          await api.admin.updateUserRole(user.user_id, role.role_id),
          isUserResponse,
          "PATCH /admin/users/{user_id}/role",
          lang,
        );
      }
      if (fields.is_active !== undefined) {
        updatedUser = requireApiObject(
          await api.admin.setUserActive(user.user_id, fields.is_active),
          isUserResponse,
          "PATCH /admin/users/{user_id}/active",
          lang,
        );
      }
      if (updatedUser) setUsers((items) => items.map((item) => item.user_id === user.user_id ? updatedUser : item));
    } catch (reason) { setError(reason.message); }
  }

  return <div className="mx-auto max-w-[1160px] px-4 py-8 md:px-8">
    <PageHeading eyebrow={`${t.eyebrowUsers} · 03`} title={t.users} intro={t.usersIntro} />
    <div className="mt-7 flex flex-wrap items-center justify-between gap-3">
      <span className="rounded-full bg-[#edf0e9] px-3 py-1 text-xs font-semibold text-[#526750]">{loading ? "…" : users.length}</span>
      <Button disabled={loading || roles.length === 0} onClick={() => setCreateOpen(!createOpen)}><Plus size={16} />{t.addUser}</Button>
    </div>
    {!loading && roles.length === 0 && <p role="status" className="mt-4 rounded-lg border border-[#e7d8bd] bg-[#f7f0e2] px-4 py-3 text-sm text-[#765b32]">{t.noRoles}</p>}
    {createOpen && <form onSubmit={addUser} className="mt-4 grid gap-4 rounded-xl border border-[#dfe1d7] bg-[#fbfaf6] p-5 shadow-sm md:grid-cols-2 md:p-6">
      <div className="md:col-span-2"><h2 className="font-bold text-[#30382e]">{t.createUser}</h2><p className="mt-1 text-xs text-[#777b70]">{t.usersIntro}</p></div>
      <Field label={t.username} required value={newUser.username} onChange={(event) => setNewUser({ ...newUser, username: event.target.value })} />
      <Field label={t.fullName} required value={newUser.full_name} onChange={(event) => setNewUser({ ...newUser, full_name: event.target.value })} />
      <Field label={t.password} type="password" required minLength={MIN_PASSWORD} value={newUser.password} onChange={(event) => setNewUser({ ...newUser, password: event.target.value })} />
      <label className="grid gap-1.5 text-sm font-semibold">{t.role}<select required value={newUser.role_id} onChange={(event) => setNewUser({ ...newUser, role_id: event.target.value })} className="focus-ring h-11 rounded-md border border-[#dedfd5] bg-white px-3"><option value="">{t.chooseRole}</option>{roles.map((item) => <option key={item.role_id} value={item.role_id}>{roleLabel(item.name, t)}</option>)}</select></label>
      <div className="flex gap-2 md:col-span-2"><Button>{t.createUser}</Button><Button type="button" variant="outline" onClick={() => setCreateOpen(false)}>{t.cancel}</Button></div>
    </form>}
    <section className="mt-6 overflow-hidden rounded-xl border border-[#e3e3da] bg-[#fbfaf6] shadow-sm">
      <div className="flex items-center justify-between border-b border-[#e9e9e2] px-5 py-4"><h2 className="font-bold text-[#30382e]">{t.users}</h2><span className="text-xs text-[#777b70]">{loading ? "…" : users.length}</span></div>
      {loading ? <p role="status" className="px-5 py-10 text-center text-sm text-[#777b70]">{t.loadingData}</p> : users.length === 0 ? <p className="px-5 py-12 text-center text-sm text-[#777b70]">{t.noUsers}</p> : users.map((user) => <div key={user.user_id} className="grid gap-3 border-b border-[#e9e9e2] px-5 py-4 last:border-b-0 md:grid-cols-[1.5fr_1fr_150px_120px] md:items-center">
        <div><div dir="auto" className="font-semibold text-[#31392f]">{user.full_name}</div><div className="text-xs text-[#81857a]">@{user.username}</div><div className="mt-1 text-[10px] text-[#92958b]">{new Date(user.created_at).toLocaleDateString(lang === "ar" ? "ar-MA" : "fr-FR")}</div></div>
        <select aria-label={t.role} disabled={loading} value={user.role} onChange={(event) => updateUser(user, { role: event.target.value })} className="focus-ring h-9 max-w-48 rounded border border-[#dedfd5] bg-white px-2 text-sm">{roles.map((item) => <option key={item.role_id} value={item.name}>{roleLabel(item.name, t)}</option>)}</select>
        <span className={`text-xs font-semibold ${user.is_active ? "text-[#527c56]" : "text-[#a54132]"}`}>{user.is_active ? t.active : t.disabled}</span>
        <button disabled={loading} onClick={() => updateUser(user, { is_active: !user.is_active })} className="focus-ring justify-self-start rounded border border-[#dedfd5] bg-white px-3 py-2 text-xs font-semibold text-[#4c554a] disabled:cursor-not-allowed disabled:opacity-50">{user.is_active ? t.disabled : t.active}</button>
      </div>)}
    </section>
  </div>;
}

export function AdminRequestsPage() {
  const { lang } = useApp();
  const { requests, setRequests, setUsers, roles, loading, setError } = useAdmin();
  const t = copy[lang];
  const [selectedRoles, setSelectedRoles] = useState({});
  const [confirmAction, setConfirmAction] = useState(null);

  async function decide(request, decision) {
    const roleName = selectedRoles[request.request_id];
    const role = roles.find((item) => item.name === roleName);
    try {
      if (decision === "approve") {
        if (!role) throw new Error(t.chooseRole);
        requireApiObject(
          await api.admin.decideAccountRequest(request.request_id, decision, role.role_id),
          (response) => isAccountRequestResponse(response) && response.status === "approved",
          "POST /admin/account-requests/{request_id}/approve",
          lang,
        );
      } else {
        requireApiObject(
          await api.admin.decideAccountRequest(request.request_id, decision),
          (response) => isAccountRequestResponse(response) && response.status === "rejected",
          "POST /admin/account-requests/{request_id}/reject",
          lang,
        );
      }
      setRequests((items) => items.filter((item) => item.request_id !== request.request_id));
      setConfirmAction(null);
      if (decision === "approve") {
        setUsers(requireApiList(await api.admin.users(), isUserResponse, "/admin/users", lang));
      }
    } catch (reason) { setError(reason.message); }
  }

  return <div className="mx-auto max-w-[1160px] px-4 py-8 md:px-8">
    <PageHeading eyebrow={`${t.eyebrowRequests} · 03`} title={t.requests} intro={t.requestsIntro} />
    <section className="mt-7 overflow-hidden rounded-xl border border-[#e3e3da] bg-[#fbfaf6] shadow-sm">
      <div className="flex items-center justify-between border-b border-[#e9e9e2] px-5 py-4"><h2 className="font-bold text-[#30382e]">{t.requests}</h2><span className="rounded-full bg-[#f3eddf] px-3 py-1 text-xs font-semibold text-[#896a34]">{loading ? "…" : requests.length}</span></div>
      {loading ? <p role="status" className="px-5 py-10 text-center text-sm text-[#777b70]">{t.loadingData}</p> : requests.length === 0 ? <p className="px-5 py-12 text-center text-sm text-[#777b70]">{t.noRequests}</p> : requests.map((request) => <article key={request.request_id} className="border-b border-[#e9e9e2] p-5 last:border-b-0">
        <div className="grid gap-4 md:grid-cols-[1.3fr_1fr_180px_auto] md:items-center">
          <div><div dir="auto" className="font-semibold text-[#31392f]">{request.full_name}</div><div className="text-xs text-[#81857a]">@{request.username}</div></div>
          <time className="text-xs text-[#777b70]">{new Date(request.created_at).toLocaleString(lang === "ar" ? "ar-MA" : "fr-FR")}</time>
          <select aria-label={t.chooseRole} disabled={loading || roles.length === 0} value={selectedRoles[request.request_id] || ""} onChange={(event) => setSelectedRoles((items) => ({ ...items, [request.request_id]: event.target.value }))} className="focus-ring h-10 rounded border border-[#dedfd5] bg-white px-2 text-sm disabled:opacity-50"><option value="">{t.chooseRole}</option>{roles.map((item) => <option key={item.role_id} value={item.name}>{roleLabel(item.name, t)}</option>)}</select>
          <div className="flex flex-wrap gap-2"><Button disabled={loading || roles.length === 0} className="h-9 min-h-9 px-3 text-xs" onClick={() => setConfirmAction({ requestId: request.request_id, decision: "approve" })}><Check size={14} />{t.approve}</Button><Button disabled={loading} variant="outline" className="h-9 min-h-9 px-3 text-xs" onClick={() => setConfirmAction({ requestId: request.request_id, decision: "reject" })}>{t.reject}</Button></div>
        </div>
        {confirmAction?.requestId === request.request_id && <div role="status" className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[#e3e3da] bg-white p-4">
          <p className="text-sm text-[#4c554a]">{confirmAction.decision === "approve" ? t.approveRequestPrompt : t.rejectRequestPrompt}</p>
          <div className="flex gap-2"><Button disabled={loading} variant={confirmAction.decision === "reject" ? "danger" : "primary"} onClick={() => decide(request, confirmAction.decision)}>{confirmAction.decision === "approve" ? t.confirmApprove : t.confirmReject}</Button><Button disabled={loading} variant="outline" onClick={() => setConfirmAction(null)}>{t.cancel}</Button></div>
        </div>}
      </article>)}
    </section>
  </div>;
}

export function AdminWebPage() {
  const { lang } = useApp();
  const { roles, setRoles, loading, setError } = useAdmin();
  const t = copy[lang];
  async function setWeb(role) {
    try {
      const updatedRole = requireApiObject(
        await api.admin.setRoleWeb(role.role_id, !role.web_enabled),
        isRoleResponse,
        "PATCH /admin/roles/{role_id}/web",
        lang,
      );
      setRoles((items) => items.map((item) => item.role_id === role.role_id ? updatedRole : item));
    } catch (reason) { setError(reason.message); }
  }
  return <div className="mx-auto max-w-[900px] px-4 py-8 md:px-8">
    <PageHeading eyebrow={`${t.eyebrowWeb} · 03`} title={t.roleWeb} intro={t.webIntro} />
    <section className="mt-8 overflow-hidden rounded-xl border border-[#e3e3da] bg-[#fbfaf6] shadow-sm">
      {loading ? <p role="status" className="px-5 py-10 text-center text-sm text-[#777b70]">{t.loadingData}</p> : roles.length === 0 ? <p className="px-5 py-12 text-center text-sm text-[#777b70]">{t.noRoles}</p> : roles.map((role) => <label key={role.role_id} className="flex cursor-pointer items-center justify-between gap-4 border-b border-[#e9e9e2] px-5 py-5 last:border-b-0"><span><span className="block font-semibold text-[#31392f]">{roleLabel(role.name, t)}</span><span className="mt-1 block text-xs text-[#81857a]">{t.allowWeb}</span></span><input type="checkbox" disabled={loading} checked={role.web_enabled} onChange={() => setWeb(role)} className="h-5 w-5 accent-[#245c48] disabled:cursor-not-allowed disabled:opacity-50" /></label>)}
    </section>
  </div>;
}

export function AdminAuditPage() {
  const { lang } = useApp();
  const { audit, loading, users, docs } = useAdmin();
  const t = copy[lang];
  return <div className="mx-auto max-w-[1160px] px-4 py-8 md:px-8">
    <PageHeading eyebrow={`${t.eyebrowAudit} · 03`} title={t.audit} intro={t.auditIntro} />
    <section className="mt-8 overflow-hidden rounded-xl border border-[#e3e3da] bg-[#fbfaf6] shadow-sm">
      {loading ? <p role="status" className="px-5 py-10 text-center text-sm text-[#777b70]">{t.loadingData}</p> : audit.length === 0 ? <p className="px-5 py-12 text-center text-sm text-[#777b70]">{t.auditEmpty}</p> : audit.map((event, index) => {
        const details = event.details && typeof event.details === "object" && !Array.isArray(event.details)
          ? Object.entries(event.details)
          : [];
        const timestamp = event.timestamp ? new Date(event.timestamp) : null;
        const dateLabel = timestamp && !Number.isNaN(timestamp.getTime())
          ? timestamp.toLocaleString(lang === "ar" ? "ar-MA" : "fr-FR")
          : "—";
        return <article key={`${event.timestamp || "event"}-${index}`} className="border-b border-[#e9e9e2] px-5 py-4 last:border-b-0">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <h2 className="text-sm font-bold text-[#526750]">{auditActionLabel(event.action, t)}</h2>
            <time className="text-xs text-[#81857a]">{dateLabel}</time>
          </div>
          <p className="mb-3 text-xs text-[#777b70]">{t.auditActor}: {auditActorLabel(event, users, t)}</p>
          {details.length === 0
            ? <p className="text-sm text-[#777b70]">{t.auditNoDetails}</p>
            : <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{details.map(([field, value]) => <div key={field} className="min-w-0"><dt className="text-[10px] font-semibold uppercase tracking-wide text-[#85887d]">{auditFieldLabel(field, t)}</dt><dd dir="auto" className={`mt-1 break-words text-sm text-[#424940] ${lang === "ar" ? "text-right" : ""}`}>{auditValue(field, value, users, docs, t)}</dd></div>)}</dl>}
        </article>;
      })}
    </section>
  </div>;
}