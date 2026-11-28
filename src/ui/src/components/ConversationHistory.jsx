import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { Plus, Trash2, X } from "lucide-react";
import { api } from "../api.js";
import { useApp } from "../app/AppContext.jsx";
import { copy } from "../app/data.js";

const ConversationContext = createContext(null);

// Saved conversations of the signed-in reader or editor, shared by the side menu (the list) and
// the chat page (the open conversation).
export function ConversationProvider({ children }) {
  const { setMessages } = useApp();
  const [conversations, setConversations] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const [historyError, setHistoryError] = useState("");

  const refreshHistory = useCallback(async () => {
    try {
      const items = await api.conversations.list();
      setConversations([...items].sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at)));
      setHistoryError("");
    } catch (reason) {
      setHistoryError(reason.message);
    }
  }, []);

  useEffect(() => {
    refreshHistory();
  }, [refreshHistory]);

  const openConversation = useCallback(async (id) => {
    try {
      const detail = await api.conversations.get(id);
      setConversationId(detail.conversation_id || detail.id);
      setMessages((detail.messages || []).map((message) => ({
        id: `${detail.conversation_id || detail.id}-${message.position}`,
        question: message.question,
        answer: message.answer,
        status: message.available ? "done" : "unavailable",
        language: message.language,
        thinking: null,
        persisted: true,
      })));
      setHistoryError("");
    } catch (reason) {
      setHistoryError(reason.message);
    }
  }, [setMessages]);

  const startNewConversation = useCallback(() => {
    setConversationId(null);
    setMessages([]);
    setHistoryError("");
  }, [setMessages]);

  const deleteConversation = useCallback(async (id) => {
    try {
      await api.conversations.remove(id);
      setConversations((items) => items.filter((item) => (item.conversation_id || item.id) !== id));
      if (conversationId === id) startNewConversation();
      return true;
    } catch (reason) {
      setHistoryError(reason.message);
      return false;
    }
  }, [conversationId, startNewConversation]);

  const conversationCreated = useCallback((conversation) => {
    const id = conversation.conversation_id || conversation.id;
    setConversationId(id);
    setConversations((items) => [conversation, ...items.filter((item) => (item.conversation_id || item.id) !== id)]);
  }, []);

  const value = useMemo(() => ({
    conversations, conversationId, historyError, refreshHistory, openConversation,
    startNewConversation, deleteConversation, conversationCreated,
  }), [conversations, conversationId, historyError, refreshHistory, openConversation,
    startNewConversation, deleteConversation, conversationCreated]);

  return <ConversationContext.Provider value={value}>{children}</ConversationContext.Provider>;
}

export function useConversations() {
  return useContext(ConversationContext);
}

// The list of saved conversations, shown in the side menu under « Conversation ».
// `onOpen` runs after a choice (go to the chat page, close the mobile menu).
export default function ConversationHistory({ onOpen = () => {} }) {
  const { lang, busy } = useApp();
  const {
    conversations, conversationId, historyError, openConversation, startNewConversation, deleteConversation,
  } = useConversations();
  const [pendingDelete, setPendingDelete] = useState(null);
  const t = copy[lang];

  return <div id="conversation-history" className="mt-1 grid min-w-0 grid-cols-1 gap-1 border-s border-[#e3e3da] ps-2 ms-5">
    <button disabled={busy} onClick={() => { startNewConversation(); onOpen(); }} className="focus-ring flex min-h-9 min-w-0 items-center gap-2 rounded-md px-2 text-start text-xs font-semibold text-[#245c48] hover:bg-[#f0f0ea] disabled:opacity-55"><Plus size={14} className="shrink-0" /><span className="truncate">{t.newConversation}</span></button>
    {conversations.length === 0 ? <p className="px-2 py-2 text-[11px] leading-5 text-[#85887d]">{t.noHistory}</p> : <ul className="grid max-h-[45vh] min-w-0 grid-cols-1 gap-0.5 overflow-y-auto scrollbar-thin">
      {conversations.map((conversation) => {
        const id = conversation.conversation_id || conversation.id;
        return <li key={id} className={`group min-w-0 rounded-md ${conversationId === id ? "bg-[#e9eee7]" : "hover:bg-[#f0f0ea]"}`}>
          <div className="flex min-w-0 items-center gap-1">
            <button disabled={busy} onClick={() => { openConversation(id); onOpen(); }} aria-current={conversationId === id ? "page" : undefined} className="focus-ring min-w-0 flex-1 rounded-md px-2 py-1.5 text-start">
              <span dir="auto" className="block truncate text-xs font-semibold text-[#3d443a]">{conversation.title || t.newConversation}</span>
              <time className="block text-[10px] text-[#85887d]">{new Date(conversation.updated_at || conversation.created_at).toLocaleDateString(lang === "ar" ? "ar-MA" : "fr-FR")}</time>
            </button>
            {pendingDelete === id ? <span className="flex shrink-0 items-center gap-0.5">
              <button onClick={async () => { if (await deleteConversation(id)) setPendingDelete(null); }} className="focus-ring rounded px-1.5 py-1 text-[10px] font-semibold text-[#a54132]">{t.confirm}</button>
              <button aria-label={t.cancel} onClick={() => setPendingDelete(null)} className="focus-ring rounded p-1 text-[#777b70]"><X size={13} /></button>
            </span> : <button disabled={busy} aria-label={t.deleteConversation} title={t.deleteConversation} onClick={() => setPendingDelete(id)} className="focus-ring shrink-0 rounded-md p-1.5 text-[#a54132] opacity-60 hover:bg-[#f7e9e5] hover:opacity-100"><Trash2 size={13} /></button>}
          </div>
        </li>;
      })}
    </ul>}
    {historyError && <p role="alert" className="px-2 text-[11px] text-[#a54132]">{historyError}</p>}
  </div>;
}
