import ChatView from "../../components/ChatView.jsx";
import { useApp } from "../../app/AppContext.jsx";
import { copy } from "../../app/data.js";

export default function ChatPage() {
  const { lang, demo, webEnabled, messages, setMessages, busy, setBusy } = useApp();
  return <ChatView lang={lang} t={copy[lang]} demo={demo} webEnabled={webEnabled} messages={messages} setMessages={setMessages} busy={busy} setBusy={setBusy} />;
}