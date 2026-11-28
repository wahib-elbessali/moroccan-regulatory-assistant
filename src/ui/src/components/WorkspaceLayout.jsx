import { useEffect, useState } from "react";
import {
  Activity, BookOpen, FileText, Globe2, LayoutDashboard, Languages, LogOut,
  Menu, MessageSquareText, UserRound, UserRoundCheck, Users, X,
} from "lucide-react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useApp } from "../app/AppContext.jsx";
import { copy, roleLabel } from "../app/data.js";

export default function WorkspaceLayout() {
  const { lang, setLang, user, error, setError, webEnabled, setWebEnabled, webAvailable, logout } = useApp();
  const t = copy[lang];
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const role = user.role;
  const isChatPage = role !== "admin" && location.pathname.endsWith("/chat");
  const chatSidebarSide = lang === "ar" ? "right-0" : "left-0";
  const closedSidebarTranslation = lang === "ar" ? "translate-x-full" : "-translate-x-full";
  const [navigationHidden, setNavigationHidden] = useState(isChatPage);
  useEffect(() => {
    setNavigationHidden(isChatPage);
  }, [isChatPage, location.pathname]);
  const root = role === "admin" ? "/admin" : `/${role}`;
  const workspaceLabel = role === "admin" ? t.adminSpace : role === "editeur" ? t.editorSpace : t.readerSpace;
  const workspaceIndex = role === "admin" ? "03" : role === "editeur" ? "02" : "01";
  const links = role === "admin"
    ? [
        ["/admin", t.overview, LayoutDashboard], ["/admin/users", t.users, Users],
        ["/admin/requests", t.requests, UserRoundCheck], ["/admin/documents", t.docRights, FileText],
        ["/admin/web", t.web, Globe2], ["/admin/audit", t.audit, Activity],
      ]
    : [[`${root}/chat`, t.chat, MessageSquareText], [`${root}/documents`, t.documents, FileText]];
  const currentPage = links.find(([path]) => path === location.pathname)?.[1] || t.app;

  function signOut() {
    logout();
    navigate("/login", { replace: true });
  }

  return <div className="app-shell min-h-screen bg-[#f6f5f0]" dir={lang === "ar" ? "rtl" : "ltr"}>
    <div className="flex min-h-screen">
      {mobileOpen && <button aria-label={t.closeMenu} onClick={() => setMobileOpen(false)} className="fixed inset-0 z-30 bg-black/25 lg:hidden" />}
      {isChatPage && !navigationHidden && <button aria-label={t.hideNavigation} onClick={() => setNavigationHidden(true)} className="fixed inset-0 z-30 hidden bg-black/25 lg:block" />}
      <aside className={`fixed inset-y-0 z-40 flex w-[264px] flex-col border-e border-[#e3e3da] bg-[#fbfaf6] p-4 transition-transform ${isChatPage ? `${chatSidebarSide} lg:fixed` : "lg:sticky"} lg:top-0 lg:h-screen lg:self-start lg:translate-x-0 ${navigationHidden ? "lg:hidden" : ""} ${mobileOpen ? "translate-x-0" : isChatPage ? closedSidebarTranslation : lang === "ar" ? "translate-x-full" : "-translate-x-full"}`}>
        <div className="flex h-14 items-center gap-3 px-2"><span className="grid h-10 w-10 place-items-center rounded-md bg-[#245c48] text-white"><BookOpen size={20} /></span><div><div className="font-bold text-[#24352b]">{t.app}</div><div className="text-[10px] text-[#85887d]">{t.brandTagline}</div></div><button className="ms-auto rounded p-2 text-[#777b70] lg:hidden" aria-label={t.closeMenu} onClick={() => setMobileOpen(false)}><X size={17} /></button></div>
        <div className="mb-3 mt-9 px-3 text-[10px] font-bold uppercase tracking-[.14em] text-[#92958b]">{role === "admin" ? t.administration : t.personalSpace}</div>
        <nav className="grid gap-1">{links.map(([path, label, Icon]) => <NavLink key={path} to={path} end={path === "/admin"} onClick={() => setMobileOpen(false)} className={({ isActive }) => `focus-ring flex h-11 items-center gap-3 rounded-md px-3 text-sm font-semibold transition ${isActive ? "bg-[#e9eee7] text-[#245c48]" : "text-[#62685e] hover:bg-[#f0f0ea]"}`}><Icon size={18} strokeWidth={1.8} />{label}</NavLink>)}</nav>
        <div className="mt-auto border-t border-[#e3e3da] pt-4"><div className="mb-2 flex items-center gap-3 rounded-md bg-[#f1f1eb] p-3"><span className="grid h-9 w-9 place-items-center rounded-full bg-[#dbe4d9] text-[#245c48]"><UserRound size={17} /></span><div className="min-w-0"><div className="truncate text-xs font-bold">{roleLabel(role, t)}</div><div className="text-[10px] text-[#85887d]">{user.username}</div></div></div><button onClick={signOut} className="focus-ring flex h-10 w-full items-center gap-3 rounded-md px-3 text-sm text-[#76796f] hover:bg-[#f0f0ea] hover:text-[#a54132]"><LogOut size={17} />{t.signOut}</button></div>
      </aside>
      <main className="min-w-0 flex-1">
        <header className="sticky top-0 z-20 flex h-[68px] items-center justify-between border-b border-[#e3e3da] bg-[#f8f7f2]/95 px-4 backdrop-blur md:px-8">
          <div className="flex items-center gap-3"><button className="focus-ring rounded-md p-2 text-[#5f655c] hover:bg-[#ebebe4] lg:hidden" onClick={() => setMobileOpen(true)} aria-label={t.showNavigation}><Menu size={20} /></button><button className="focus-ring hidden rounded-md p-2 text-[#5f655c] hover:bg-[#ebebe4] lg:inline-flex" onClick={() => setNavigationHidden((hidden) => !hidden)} aria-label={navigationHidden ? t.showNavigation : t.hideNavigation} title={navigationHidden ? t.showNavigation : t.hideNavigation}><Menu size={19} /></button><div><div className="text-[10px] font-bold uppercase tracking-[.12em] text-[#9b6b4c]">{workspaceLabel} · {workspaceIndex}</div><div className="text-sm font-bold text-[#32392f]">{currentPage}</div></div></div>
          <div className="flex items-center gap-2 md:gap-4">
            {role !== "admin" && webAvailable && <label className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-xs text-[#5f655c]" title={t.useWeb}><Globe2 size={16} /><span className="hidden sm:inline">{t.useWeb}</span><input aria-label={t.useWeb} type="checkbox" checked={webEnabled} onChange={(event) => setWebEnabled(event.target.checked)} className="h-4 w-4 accent-[#245c48]" /></label>}
            <span className="hidden items-center gap-1.5 text-xs text-[#777b70] sm:flex"><span className="h-2 w-2 rounded-full bg-[#6c9a69]" />{t.activeNow}</span>
            <button onClick={() => setLang(lang === "ar" ? "fr" : "ar")} className="focus-ring inline-flex h-9 items-center gap-1.5 rounded-md border border-[#e3e3da] bg-white px-2.5 text-xs font-semibold text-[#4c554a]"><Languages size={15} />{lang === "ar" ? "FR" : "عربي"}</button>
          </div>
        </header>
        {error && <div role="alert" className="mx-4 mt-4 flex items-center justify-between rounded-md border border-[#eed1c8] bg-[#f8e9e5] px-4 py-3 text-sm text-[#9b4435] md:mx-8"><span>{error}</span><button onClick={() => setError("")} aria-label="Fermer" className="focus-ring rounded p-1"><X size={16} /></button></div>}
        <Outlet />
      </main>
    </div>
  </div>;
}