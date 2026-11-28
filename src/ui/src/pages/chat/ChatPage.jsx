import ChatView from "../../components/ChatView.jsx";
import { useConversations } from "../../components/ConversationHistory.jsx";
import { useApp } from "../../app/AppContext.jsx";
import { copy } from "../../app/data.js";

// The saved conversations are listed in the side menu (ConversationHistory); this page shows the
// open one.
export default function ChatPage() {
  const { lang, webEnabled, messages, setMessages, busy, setBusy, setError } = useApp();
  const { conversationId, conversationCreated, refreshHistory } = useConversations();
  const t = copy[lang];

  return <div className="min-w-0">
    <ChatView
      lang={lang}
      t={t}
      webEnabled={webEnabled}
      messages={messages}
      setMessages={setMessages}
      busy={busy}
      setBusy={setBusy}
      conversationId={conversationId}
      onConversationCreated={conversationCreated}
      onMessageSaved={refreshHistory}
      onPersistenceError={setError}
    />
  </div>;
}
