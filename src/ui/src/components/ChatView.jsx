import { useEffect, useRef, useState } from "react";
import {
  Activity, ArrowLeft, BookOpen, Check, ChevronDown, ChevronLeft, Send,
  ShieldCheck, Sparkles, X,
} from "lucide-react";
import { api } from "../api.js";
import { copy, MAX_QUESTION_CHARS } from "../app/data.js";
import { appendThinkingFragment, emptyThinking } from "../app/thinking.js";

function CitationText({ text, citations, onCitation }) {
  const parts = text.split(/(\[\d+\])/g);
  return <>{parts.map((part, index) => {
    const marker = part.match(/^\[(\d+)\]$/);
    if (!marker) return <span key={index}>{part}</span>;
    const number = Number(marker[1]);
    return <button key={index} className="focus-ring mx-0.5 inline-flex h-6 min-w-6 items-center justify-center rounded-full bg-[#dce9de] px-1.5 align-middle text-xs font-bold text-[#245c48] hover:bg-[#c9ddcc]" onClick={() => onCitation(citations[number - 1])}><bdi>[{number}]</bdi></button>;
  })}</>;
}

export default function ChatView({
  lang, t, webEnabled, messages, setMessages, busy, setBusy,
  conversationId, onConversationCreated, onMessageSaved, onPersistenceError,
}) {
  const [question, setQuestion] = useState("");
  const [error, setError] = useState("");
  const [selectedCitation, setSelectedCitation] = useState(null);
  const [thinkingOpen, setThinkingOpen] = useState({});
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  async function submit(event) {
    event.preventDefault();
    const clean = question.trim();
    if (!clean || clean.length > MAX_QUESTION_CHARS) return setError(t.questionLimit.replace("{max}", String(MAX_QUESTION_CHARS)));
    setError(""); setQuestion(""); setBusy(true);
    const id = crypto.randomUUID();
    setMessages((items) => [...items, { id, question: clean, thinking: emptyThinking(), answer: null, status: "working" }]);
    const addThinking = (text) => setMessages((items) => items.map((item) => item.id === id ? { ...item, thinking: appendThinkingFragment(item.thinking, text) } : item));
    const setAnswer = (answer) => setMessages((items) => items.map((item) => item.id === id ? { ...item, answer, status: "done" } : item));

    try {
      let activeConversationId = conversationId;
      if (!activeConversationId) {
        const conversation = await api.conversations.create();
        activeConversationId = conversation.conversation_id || conversation.id;
        if (!activeConversationId) throw new Error("La création de la conversation n'a pas renvoyé d'identifiant.");
        onConversationCreated(conversation);
      }
      let answer;
      await api.ask(clean, webEnabled, ({ event, data }) => {
        if (event === "thinking") addThinking(data.text);
        if (event === "answer") {
          answer = data;
          setAnswer(data);
        }
        if (event === "error") {
          answer = null;
          setAnswer({ status: "error", text: data.message });
        }
      });
      if (answer) {
        try {
          await api.conversations.addMessage(activeConversationId, clean, answer);
          await onMessageSaved();
        } catch (reason) {
          onPersistenceError(reason.message || t.unavailable);
        }
      }
    } catch (reason) {
      setAnswer({ status: "error", text: reason.code === "STREAM_INTERRUPTED" ? t.interrupted : reason.message || t.unavailable });
    } finally { setBusy(false); }
  }

  return <div className="mx-auto flex min-h-[calc(100vh-112px)] w-full max-w-[980px] flex-col px-4 pb-5 pt-6 md:px-8">
    {messages.length === 0 ? <div className="my-auto pb-16 pt-10 text-center rise-in">
      <div className="mx-auto mb-6 grid h-14 w-14 place-items-center rounded-xl border border-[#dce4d9] bg-[#e9eee7] text-[#245c48]"><BookOpen size={25} /></div>
      <span className="text-xs font-bold uppercase tracking-[.14em] text-[#b76940]">المعرفة القانونية · LE DROIT MAROCAIN</span>
      <h1 className={`mx-auto mt-3 max-w-2xl text-3xl font-semibold leading-tight text-[#25352a] md:text-4xl ${lang === "ar" ? "arabic" : ""}`}>{t.askTitle}</h1>
      <p className="mx-auto mt-3 max-w-lg text-sm leading-6 text-[#777b70]">{t.askIntro}</p>
      <div className="mx-auto mt-9 grid max-w-2xl gap-2 text-start sm:grid-cols-2">
        {(lang === "ar" ? ["ما هو أجل معالجة الطلبات الإدارية؟", "ما هي الوثائق المطلوبة لإيداع طلب؟"] : ["Quel est le délai de traitement des demandes ?", "Quelles pièces joindre à une demande ?"]).map((suggestion) => <button key={suggestion} onClick={() => setQuestion(suggestion)} className="focus-ring flex min-h-14 items-center justify-between gap-3 rounded-md border border-[#e3e3da] bg-[#fbfaf6] px-4 text-start text-sm text-[#4c554a] hover:border-[#a7b7a5] hover:bg-white"><span>{suggestion}</span><ArrowLeft size={15} className="shrink-0 text-[#9b6b4c]" /></button>)}
      </div>
    </div> : <div className="grid flex-1 content-start gap-8 pb-8">
      {messages.map((item) => <article key={item.id} className="grid gap-4 fade-in">
        <div className="flex justify-end"><div dir="auto" className="max-w-[85%] rounded-2xl rounded-br-sm bg-[#e6ebe2] px-4 py-3 text-[15px] leading-7 text-[#29382c]">{item.question}</div></div>
        <div className="flex items-start gap-3"><span className="mt-1 grid h-8 w-8 shrink-0 place-items-center rounded-md bg-[#245c48] text-white"><Sparkles size={15} /></span><div className="min-w-0 flex-1 pt-1">
          {item.thinking && <details open={item.status === "working" || thinkingOpen[item.id] === true} onToggle={(event) => { const isOpen = event.currentTarget.open; setThinkingOpen((value) => ({ ...value, [item.id]: isOpen })); }} className="mb-3 max-w-2xl rounded-md border border-[#e3e3da] bg-[#fbfaf6]">
            <summary className="focus-ring flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 text-xs font-semibold text-[#646b60]"><Activity size={14} className={item.status === "working" ? "animate-pulse text-[#b76940]" : "text-[#789078]"} />{t.thinking}<ChevronDown size={14} className="ms-auto" /></summary>
            <div className="grid gap-2 border-t border-[#e3e3da] px-3 py-3">{[...item.thinking.lines, item.thinking.current].filter((line) => line.length > 0).map((line, index) => <p key={index} dir="auto" className="flex items-start gap-2 text-xs leading-5 text-[#777b70]"><Check size={13} className="mt-0.5 shrink-0 text-[#6b906b]" />{line}</p>)}{item.status === "working" && <span className="h-1 w-12 animate-pulse rounded bg-[#d2b69a]" />}</div>
          </details>}
          {item.status === "unavailable" ? <p dir="auto" className={`max-w-3xl text-sm leading-7 text-[#777b70] ${item.language === "ar" ? "arabic" : ""}`}>{item.language === "ar" ? t.unavailableAnswerAr : t.unavailableAnswer}</p> : !item.answer ? <div className="flex items-center gap-2 py-2 text-sm text-[#777b70]"><span className="h-2 w-2 animate-pulse rounded-full bg-[#b76940]" />{lang === "ar" ? "جارٍ إعداد الإجابة…" : "Préparation de la réponse…"}</div> : item.answer.status === "unknown" ? <p dir="auto" className={`max-w-3xl text-[15px] leading-8 text-[#30382e] ${item.answer.language === "ar" ? "arabic" : ""}`}>{item.answer.text}</p> : item.answer.status === "error" ? <p role="alert" dir="auto" className="rounded-md bg-[#f8e9e5] px-3 py-2 text-sm text-[#9b4435]">{item.answer.text}</p> : <div className="max-w-3xl">
            {(() => {
              const citations = item.answer.citations || [];
              const hasWebCitation = citations.some((citation) => citation.url);
              const [firstLine, ...remainingLines] = item.answer.text.split("\n");
              const hasWebNotice = hasWebCitation && remainingLines.length > 0;
              return <>
                {hasWebNotice && <div dir="auto" className="mb-3 border-s-2 border-[#c56e3d] bg-[#f6eee7] px-3 py-2 text-xs font-semibold text-[#885232]">{firstLine}</div>}
                <p dir="auto" className={`text-[15px] leading-8 text-[#30382e] ${item.answer.language === "ar" ? "arabic" : ""}`}><CitationText text={hasWebNotice ? remainingLines.join("\n") : item.answer.text} citations={citations} onCitation={setSelectedCitation} /></p>
                {citations.length > 0 && <div className="mt-5 border-t border-[#e3e3da] pt-3"><h3 className="mb-2 text-xs font-bold uppercase tracking-[.1em] text-[#777b70]">{t.sources} · {citations.length}</h3><div className="grid gap-2">{citations.map((citation, index) => <button key={index} onClick={() => setSelectedCitation(citation)} className="focus-ring flex items-center gap-3 rounded-md border border-[#e3e3da] bg-[#fbfaf6] p-3 text-start hover:bg-white"><span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[#e6ebe2] text-xs font-bold text-[#245c48]"><bdi>{index + 1}</bdi></span><span className="min-w-0"><span dir="auto" className="block truncate text-sm font-semibold text-[#3a4137]">{citation.title}</span><span dir="auto" className="mt-1 block text-xs text-[#777b70]">{[citation.article, citation.page && `${item.answer.language === "ar" ? "ص" : "p."} ${citation.page}`, citation.source].filter(Boolean).join(" · ")}</span>{citation.url && <span className="mt-1 inline-block rounded bg-[#f6eee7] px-1.5 py-0.5 text-[10px] font-semibold text-[#885232]">{t.webSource}</span>}</span><ChevronLeft size={16} className="ms-auto shrink-0 text-[#8b9085]" /></button>)}</div></div>}
              </>;
            })()}
            {item.answer.status === "answered" && <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-[#777b70]"><span className="inline-flex items-center gap-1.5"><ShieldCheck size={14} className="text-[#6b906b]" />{copy[item.answer.language === "ar" ? "ar" : "fr"].verify}</span><span>{t.confidence}: <bdi>{Math.round((item.answer.confidence || 0) * 100)}%</bdi></span></div>}
          </div>}
        </div></div>
      </article>)}<div ref={bottomRef} />
    </div>}
    {selectedCitation && <div className="mb-4 rounded-md border border-[#dfe2d8] bg-white p-4 shadow-sm fade-in" dir="auto"><div className="flex items-start justify-between gap-4"><div><div className="text-[10px] font-bold uppercase tracking-[.12em] text-[#b76940]">{t.sources}</div><h3 className="mt-1 font-bold text-[#30382e]">{selectedCitation.title}</h3></div><button aria-label="Fermer" onClick={() => setSelectedCitation(null)} className="focus-ring rounded p-1 text-[#777b70]"><X size={17} /></button></div><p className="mt-2 text-xs text-[#777b70]">{[selectedCitation.article, selectedCitation.page && `p. ${selectedCitation.page}`, selectedCitation.source].filter(Boolean).join(" · ")}</p><blockquote className="mt-3 border-s-2 border-[#94a68d] ps-3 text-sm leading-6 text-[#454b42]">{selectedCitation.excerpt}</blockquote>{selectedCitation.url?.match(/^https?:\/\//) && <a className="mt-3 inline-block text-sm font-semibold text-[#245c48] underline" href={selectedCitation.url} target="_blank" rel="noopener noreferrer">Source web ↗</a>}</div>}
    <form onSubmit={submit} className="sticky bottom-0 border border-[#dedfd5] bg-white p-2 shadow-[0_8px_32px_rgba(38,47,37,.08)] md:rounded-xl md:p-3">
      <textarea dir="auto" rows="2" maxLength={MAX_QUESTION_CHARS} value={question} onChange={(event) => { setQuestion(event.target.value); setError(""); }} placeholder={t.askPlaceholder} className={`focus-ring max-h-36 min-h-14 w-full resize-y border-0 bg-transparent px-2 py-2 text-sm leading-6 text-[#30382e] placeholder:text-[#92958b] outline-none ${lang === "ar" ? "arabic" : ""}`} />
      <div className="flex items-center justify-between border-t border-[#efefe9] pt-2"><span className="text-[11px] text-[#92958b]">{question.length}/{MAX_QUESTION_CHARS}{error && <span role="alert" className="ms-3 text-[#a54132]">{error}</span>}</span><button type="submit" disabled={busy || !question.trim()} className="focus-ring inline-flex h-9 min-h-9 items-center justify-center gap-2 rounded-md bg-[#245c48] px-3 text-sm font-semibold text-white hover:bg-[#193e33] disabled:cursor-not-allowed disabled:opacity-55">{busy ? <Activity size={16} className="animate-pulse" /> : <Send size={15} />}{t.send}</button></div>
    </form>
  </div>;
}