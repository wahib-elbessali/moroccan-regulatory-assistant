import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { api, isDemoMode, saveToken } from "../api.js";
import { copy, initialDocs } from "./data.js";

const AppContext = createContext(null);

export function AppProvider({ children }) {
  const [lang, setLang] = useState("ar");
  const [user, setUser] = useState(null);
  const [error, setError] = useState("");
  const [webEnabled, setWebEnabledState] = useState(() => localStorage.getItem("assistant-web-enabled") !== "false");
  const [webAvailable, setWebAvailable] = useState(true);
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [docs, setDocs] = useState(initialDocs);
  const demo = isDemoMode();

  function setWebEnabled(enabled) {
    localStorage.setItem("assistant-web-enabled", String(enabled));
    setWebEnabledState(enabled);
  }

  useEffect(() => {
    const handleUnauthorized = () => {
      setUser(null);
      setMessages([]);
      setError(copy[lang].sessionExpired);
    };
    window.addEventListener("assistant:unauthorized", handleUnauthorized);
    return () => window.removeEventListener("assistant:unauthorized", handleUnauthorized);
  }, [lang]);

  async function login(username, password) {
    const profile = await api.auth.login(username, password);
    setUser(profile);
    setWebAvailable(profile.web_available);
    setWebEnabled(profile.web_available);
    setError("");
    setMessages([]);
    const documents = await api.documents.list().catch(() => []);
    setDocs(documents);
    return profile;
  }

  function startDemo(role) {
    setUser({ user_id: `demo-${role}`, username: "demo@local", role, web_enabled: true, request_id: crypto.randomUUID() });
    setWebAvailable(role !== "admin");
    setWebEnabled(true);
    setMessages([]);
    setError("");
    setDocs(initialDocs);
  }

  function logout() {
    saveToken(null);
    setUser(null);
    setMessages([]);
    setError("");
  }

  const value = useMemo(() => ({
    lang, setLang, user, error, setError, webEnabled, setWebEnabled, webAvailable,
    messages, setMessages, busy, setBusy, docs, setDocs, demo, login, startDemo, logout,
  }), [lang, user, error, webEnabled, webAvailable, messages, busy, docs, demo]);

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const value = useContext(AppContext);
  if (!value) throw new Error("useApp must be used inside AppProvider");
  return value;
}