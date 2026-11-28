import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { api, getToken, saveToken } from "../api.js";
import { copy, initialDocs } from "./data.js";

const AppContext = createContext(null);

export function AppProvider({ children }) {
  const [lang, setLang] = useState(() => localStorage.getItem("assistant-language") === "fr" ? "fr" : "ar");
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [error, setError] = useState("");
  const [webEnabled, setWebEnabledState] = useState(() => localStorage.getItem("assistant-web-enabled") !== "false");
  const [webAvailable, setWebAvailable] = useState(true);
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [docs, setDocs] = useState(initialDocs);
  useEffect(() => {
    localStorage.setItem("assistant-language", lang);
  }, [lang]);

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

  useEffect(() => {
    let active = true;
    async function restoreSession() {
      if (!getToken()) {
        setAuthLoading(false);
        return;
      }
      try {
        const profile = await api.auth.me();
        if (!active) return;
        setUser(profile);
        setWebAvailable(profile.web_available);
        setWebEnabledState(profile.web_available && localStorage.getItem("assistant-web-enabled") !== "false");
        try {
          const documents = await api.documents.list();
          if (active) setDocs(documents);
        } catch (reason) {
          if (active) setError(reason.message);
        }
      } catch (reason) {
        if (active && reason.status !== 401) setError(reason.message);
      } finally {
        if (active) setAuthLoading(false);
      }
    }
    restoreSession();
    return () => { active = false; };
  }, []);

  async function login(username, password) {
    const profile = await api.auth.login(username, password);
    setUser(profile);
    setWebAvailable(profile.web_available);
    setWebEnabledState(profile.web_available && localStorage.getItem("assistant-web-enabled") !== "false");
    setError("");
    setMessages([]);
    try {
      setDocs(await api.documents.list());
    } catch (reason) {
      setDocs([]);
      setError(reason.message);
    }
    return profile;
  }

  function logout() {
    saveToken(null);
    setUser(null);
    setMessages([]);
    setError("");
  }

  const value = useMemo(() => ({
    lang, setLang, user, authLoading, error, setError, webEnabled, setWebEnabled, webAvailable,
    messages, setMessages, busy, setBusy, docs, setDocs, login, logout,
  }), [lang, user, authLoading, error, webEnabled, webAvailable, messages, busy, docs]);

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const value = useContext(AppContext);
  if (!value) throw new Error("useApp must be used inside AppProvider");
  return value;
}