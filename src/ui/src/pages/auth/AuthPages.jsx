import { useEffect, useState } from "react";
import { ArrowLeft, BookOpen, KeyRound, Languages } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../../api.js";
import { useApp } from "../../app/AppContext.jsx";
import { MIN_PASSWORD, copy } from "../../app/data.js";
import { Button, BusyIcon, Field } from "../../components/Ui.jsx";

function AuthShell({ children }) {
  const { lang, setLang } = useApp();
  const t = copy[lang];
  return <main className="app-shell grid min-h-screen bg-[#f6f5f0] lg:grid-cols-[1.05fr_.95fr]" dir={lang === "ar" ? "rtl" : "ltr"}>
    <section className="relative flex min-h-[48vh] flex-col justify-between overflow-hidden bg-[#193e33] px-7 py-7 text-white md:px-12 md:py-10 lg:min-h-screen lg:px-16">
      <div className="absolute inset-0 opacity-20" style={{ backgroundImage: "radial-gradient(#d5d9c7 0.7px, transparent 0.7px)", backgroundSize: "14px 14px" }} />
      <div className="relative flex items-center justify-between">
        <div className="flex items-center gap-3"><span className="grid h-11 w-11 place-items-center rounded-lg border border-white/20 bg-white/10"><BookOpen size={22} /></span><span className="text-sm font-bold tracking-wide">{t.app}</span></div>
        <button onClick={() => setLang(lang === "ar" ? "fr" : "ar")} className="focus-ring inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm text-white/80 hover:bg-white/10"><Languages size={17} />{lang === "ar" ? "FR" : "عربي"}</button>
      </div>
      <div className="relative my-12 max-w-xl lg:my-0">
        <div className="mb-6 flex items-center gap-3 text-xs font-semibold uppercase tracking-[.14em] text-[#c2d1bd]"><span className="h-px w-8 bg-[#d78b5c]" />Royaume du Maroc · النصوص التنظيمية</div>
        <h1 className={`max-w-lg text-4xl font-semibold leading-[1.22] md:text-5xl ${lang === "ar" ? "arabic" : ""}`}>{lang === "ar" ? "المعرفة القانونية، بين يديك." : "La connaissance juridique, à portée de main."}</h1>
        <p className="mt-5 max-w-md text-base leading-7 text-white/70">{lang === "ar" ? "ابحث في النصوص التنظيمية المغربية بإجابات موثقة ومراجع واضحة." : "Explorez les textes réglementaires marocains avec des réponses sourcées et vérifiables."}</p>
        <div className="mt-10 flex flex-wrap gap-2 text-xs text-[#e2e8de]"><span className="rounded border border-white/20 px-3 py-2">العربية</span><span className="rounded border border-white/20 px-3 py-2">Français</span></div>
      </div>
      <p className="relative text-xs text-white/45">© 2026 · Assistant réglementaire marocain</p>
    </section>
    <section className="flex items-center justify-center px-6 py-12 md:px-12"><div className="w-full max-w-[440px] rise-in">{children}</div></section>
  </main>;
}

export function LoginPage() {
  const { lang, user, login, error, setError } = useApp();
  const t = copy[lang];
  const navigate = useNavigate();
  const [form, setForm] = useState({ username: "", password: "" });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const update = (key) => (event) => setForm((value) => ({ ...value, [key]: event.target.value }));

  useEffect(() => {
    if (user) navigate(user.role === "admin" ? "/admin" : `/${user.role}/chat`, { replace: true });
  }, [user, navigate]);

  async function submit(event) {
    event.preventDefault(); setBusy(true); setMessage(""); setError("");
    try {
      const profile = await login(form.username, form.password);
      navigate(profile.role === "admin" ? "/admin" : `/${profile.role}/chat`, { replace: true });
    } catch (reason) { setMessage(reason.message || t.unavailable); }
    finally { setBusy(false); }
  }

  return <AuthShell>
    <div className="mb-9"><p className="text-xs font-bold uppercase tracking-[.13em] text-[#b76940]">ESPACE SÉCURISÉ</p><h2 className={`mt-2 text-3xl font-semibold text-[#242a24] ${lang === "ar" ? "arabic" : ""}`}>{t.login}</h2><p className="mt-2 text-sm leading-6 text-[#777b70]">{lang === "ar" ? "سجّل الدخول للمتابعة إلى فضائك." : "Connectez-vous pour accéder à votre espace."}</p></div>
    <form className="grid gap-4" onSubmit={submit}>
      <Field label={t.username} autoComplete="username" required minLength={3} maxLength={32} value={form.username} onChange={update("username")} />
      <Field label={t.password} type="password" autoComplete="current-password" required value={form.password} onChange={update("password")} />
      {(message || error) && <p role="alert" className="rounded-md bg-[#f8e9e5] px-3 py-2.5 text-sm text-[#9b4435]">{message || error}</p>}
      <Button type="submit" disabled={busy} className="mt-1 h-12 w-full">{busy ? <BusyIcon /> : <KeyRound size={17} />}{t.signIn}<ArrowLeft size={16} className={lang === "ar" ? "" : "rotate-180"} /></Button>
    </form>
    <Link to="/demande-compte" className="focus-ring mt-4 block w-full rounded-md py-3 text-center text-sm font-semibold text-[#245c48] hover:bg-[#e9ede5]">{t.request} →</Link>
  </AuthShell>;
}

export function AccountRequestPage() {
  const { lang, setError } = useApp();
  const t = copy[lang];
  const navigate = useNavigate();
  const [form, setForm] = useState({ username: "", full_name: "", password: "", confirm: "" });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setLocalError] = useState("");
  const update = (key) => (event) => setForm((value) => ({ ...value, [key]: event.target.value }));

  async function submit(event) {
    event.preventDefault(); setMessage(""); setLocalError(""); setError("");
    if (form.password.length < MIN_PASSWORD) return setLocalError(t.passwordShort.replace("{min}", String(MIN_PASSWORD)));
    if (form.password !== form.confirm) return setLocalError(t.passwordMismatch);
    setBusy(true);
    try {
      await api.auth.requestAccount({ username: form.username, password: form.password, full_name: form.full_name });
      setMessage(t.requestSent);
      setForm({ username: "", full_name: "", password: "", confirm: "" });
    } catch (reason) {
      setLocalError(reason.status === 409 ? t.usernameUnavailable : reason.status === 429 ? t.pendingRequestsFull : reason.message || t.unavailable);
    }
    finally { setBusy(false); }
  }

  return <AuthShell>
    <div className="mb-9"><p className="text-xs font-bold uppercase tracking-[.13em] text-[#b76940]">CRÉATION DE COMPTE</p><h2 className={`mt-2 text-3xl font-semibold text-[#242a24] ${lang === "ar" ? "arabic" : ""}`}>{t.request}</h2><p className="mt-2 text-sm leading-6 text-[#777b70]">{lang === "ar" ? "سيتم إنشاء حسابك بعد موافقة المسؤول." : "Votre compte sera créé après validation par un administrateur."}</p></div>
    <form className="grid gap-4" onSubmit={submit}>
      <Field label={t.username} autoComplete="username" required minLength={3} maxLength={32} pattern={"[A-Za-z0-9._\\-]+"} value={form.username} onChange={update("username")} />
      <Field label={t.fullName} required maxLength={100} value={form.full_name} onChange={update("full_name")} />
      <Field label={t.password} type="password" autoComplete="new-password" required minLength={MIN_PASSWORD} value={form.password} onChange={update("password")} />
      <Field label={t.repeatPassword} type="password" autoComplete="new-password" required value={form.confirm} onChange={update("confirm")} />
      {message && <p role="status" className="rounded-md bg-[#e6f1e8] px-3 py-2.5 text-sm text-[#356448]">{message}</p>}
      {error && <p role="alert" className="rounded-md bg-[#f8e9e5] px-3 py-2.5 text-sm text-[#9b4435]">{error}</p>}
      <Button type="submit" disabled={busy} className="h-12 w-full">{busy ? <BusyIcon /> : <KeyRound size={17} />}{t.sendRequest}</Button>
    </form>
    <Link to="/login" className="focus-ring mt-4 block w-full rounded-md py-3 text-center text-sm font-semibold text-[#245c48] hover:bg-[#e9ede5]">{t.login} →</Link>
  </AuthShell>;
}