import { useCallback, useEffect, useState } from "react";
import { Menu, Plus, Trash2, X } from "lucide-react";
import ChatView from "../../components/ChatView.jsx";
import { api } from "../../api.js";
import { useApp } from "../../app/AppContext.jsx";
import { copy } from "../../app/data.js";

export default function ChatPage() {
  const { lang, webEnabled, messages, setMessages, busy, setBusy, setError } = useApp();
  const [conversations, setConversations] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const [pendingDelete, setPendingDelete] = useState(null);
  const [historyError, setHistoryError] = useState("");
  const [historyOpen, setHistoryOpen] = useState(true);
  const t = copy[lang];

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

  async function openConversation(id) {
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
  }

  function startNewConversation() {
    setConversationId(null);
    setMessages([]);
    setHistoryError("");
  }

  async function deleteConversation(id) {
    try {
      await api.conversations.remove(id);
      setConversations((items) => items.filter((item) => (item.conversation_id || item.id) !== id));
      if (conversationId === id) startNewConversation();
      setPendingDelete(null);
    } catch (reason) {
      setHistoryError(reason.message);
    }
  }

  const handleConversationCreated = (conversation) => {
    const id = conversation.conversation_id || conversation.id;
    setConversationId(id);
    setConversations((items) => [conversation, ...items.filter((item) => (item.conversation_id || item.id) !== id)]);
  };

  return <div className={`grid min-h-[calc(100vh-68px)] grid-cols-1 ${historyOpen ? "md:grid-cols-[260px_minmax(0,1fr)]" : ""}`}>
    {historyOpen && <aside id="conversation-history" className="max-h-[36vh] overflow-y-auto border-b border-[#e3e3da] bg-[#fbfaf6] p-4 scrollbar-thin md:sticky md:top-[68px] md:h-[calc(100vh-68px)] md:max-h-none md:self-start md:border-b-0 md:border-e">
      <button disabled={busy} onClick={startNewConversation} className="focus-ring mb-5 flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-[#245c48] px-3 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-[#193e33]"><Plus size={16} />{t.newConversation}</button>
      <h2 className="mb-3 px-1 text-[11px] font-bold uppercase tracking-[.12em] text-[#777b70]">{t.history}</h2>
      {conversations.length === 0 ? <p className="px-1 py-3 text-xs leading-5 text-[#777b70]">{t.noHistory}</p> : <ul className="grid grid-cols-1 gap-1">
        {conversations.map((conversation) => {
          const id = conversation.conversation_id || conversation.id;
          return <li key={id} className={`group min-w-0 rounded-lg border transition-colors ${conversationId === id ? "border-[#cbd8c9] bg-[#e9eee7]" : "border-transparent hover:border-[#e3e3da] hover:bg-white"}`}>
            <div className="flex items-center gap-1 p-1">
              <button disabled={busy} onClick={() => openConversation(id)} aria-current={conversationId === id ? "page" : undefined} className="focus-ring min-h-12 min-w-0 flex-1 rounded-md px-2 py-2 text-start">
                <span dir="auto" className="block truncate text-xs font-semibold text-[#3d443a]">{conversation.title || t.newConversation}</span>
                <time className="mt-1 block text-[10px] text-[#85887d]">{new Date(conversation.updated_at || conversation.created_at).toLocaleDateString(lang === "ar" ? "ar-MA" : "fr-FR")}</time>
              </button>
              {pendingDelete === id ? <span className="flex shrink-0 items-center gap-1 pe-1">
                <button onClick={() => deleteConversation(id)} className="focus-ring rounded px-2 py-1 text-[10px] font-semibold text-[#a54132]">{t.confirm}</button>
                <button aria-label={t.cancel} onClick={() => setPendingDelete(null)} className="focus-ring rounded p-1 text-[#777b70]"><X size={14} /></button>
              </span> : <button disabled={busy} aria-label={t.deleteConversation} title={t.deleteConversation} onClick={() => setPendingDelete(id)} className="focus-ring me-1 rounded-md border border-[#ead5cf] bg-white p-2 text-[#a54132] transition-colors hover:bg-[#f7e9e5]"><Trash2 size={14} /></button>}
            </div>
          </li>;
        })}
      </ul>}
      {historyError && <p role="alert" className="mt-3 text-xs text-[#a54132]">{historyError}</p>}
    </aside>}
    <div className="min-w-0">
      <div className="flex h-11 items-center border-b border-[#e3e3da] px-4 md:px-8">
        <button aria-expanded={historyOpen} aria-controls={historyOpen ? "conversation-history" : undefined} onClick={() => setHistoryOpen((open) => !open)} className="focus-ring inline-flex h-9 items-center gap-2 rounded-md px-3 text-xs font-semibold text-[#596157] transition-colors hover:bg-[#efefe8]">
          <Menu size={16} />{historyOpen ? t.hideHistory : t.showHistory}
        </button>
      </div>
      <ChatView
        lang={lang}
        t={t}
        webEnabled={webEnabled}
        messages={messages}
        setMessages={setMessages}
        busy={busy}
        setBusy={setBusy}
        conversationId={conversationId}
        onConversationCreated={handleConversationCreated}
        onMessageSaved={refreshHistory}
        onPersistenceError={setError}
      />
    </div>
  </div>;
}