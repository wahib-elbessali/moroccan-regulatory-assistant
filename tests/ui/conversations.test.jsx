import React from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { api } from "../../src/ui/src/api.js";
import { copy } from "../../src/ui/src/app/data.js";
import ChatView from "../../src/ui/src/components/ChatView.jsx";

vi.mock("../../src/ui/src/api.js", () => ({
  api: {
    ask: vi.fn(),
    conversations: {
      create: vi.fn(),
      addMessage: vi.fn(),
    },
  },
}));

function ChatHarness({ initialMessages = [] }) {
  const [messages, setMessages] = React.useState(initialMessages);
  const [busy, setBusy] = React.useState(false);
  return <ChatView
    lang="fr"
    t={copy.fr}
    webEnabled={false}
    messages={messages}
    setMessages={setMessages}
    busy={busy}
    setBusy={setBusy}
    conversationId={null}
    onConversationCreated={vi.fn()}
    onMessageSaved={vi.fn()}
    onPersistenceError={vi.fn()}
  />;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("crypto", { randomUUID: () => "message-1" });
  HTMLElement.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("saved conversation behavior", () => {
  test("creates a conversation then saves the question and exact answer event", async () => {
    const answer = {
      status: "answered",
      text: "Réponse [1]",
      citations: [{ title: "Source", excerpt: "Extrait", article: "Article 1", page: 1, source: "BO", url: null }],
      confidence: 0.9,
      language: "fr",
    };
    api.conversations.create.mockResolvedValue({ conversation_id: "conversation-1" });
    api.ask.mockImplementation(async (_question, _useWeb, onEvent) => {
      onEvent({ event: "answer", data: answer });
    });
    api.conversations.addMessage.mockResolvedValue({});

    const user = userEvent.setup();
    render(<ChatHarness />);
    await user.type(screen.getByPlaceholderText(copy.fr.askPlaceholder), "Question test");
    await user.click(screen.getByRole("button", { name: copy.fr.send }));

    await waitFor(() => {
      expect(api.conversations.addMessage).toHaveBeenCalledWith("conversation-1", "Question test", answer);
    });
    expect(api.conversations.create).toHaveBeenCalledOnce();
    expect(api.ask).toHaveBeenCalledWith("Question test", false, expect.any(Function));
  });

  test("shows only the fixed notice when a saved answer is no longer available", () => {
    render(<ChatHarness initialMessages={[{
      id: "saved-1",
      question: "Ancienne question",
      answer: null,
      status: "unavailable",
      language: "fr",
      thinking: null,
      persisted: true,
    }]} />);

    expect(screen.getByText(copy.fr.unavailableAnswer)).toBeTruthy();
    expect(screen.queryByText(copy.fr.confidence)).toBeNull();
    expect(screen.queryByText(copy.fr.sources)).toBeNull();
  });

  test("does not add confidence, citations, or a hint to an unknown answer", () => {
    render(<ChatHarness initialMessages={[{
      id: "saved-unknown",
      question: "Question sans réponse",
      answer: { status: "unknown", text: "Réponse inconnue", citations: [], confidence: 0, language: "fr" },
      status: "done",
      thinking: null,
      persisted: true,
    }]} />);

    expect(screen.getByText("Réponse inconnue")).toBeTruthy();
    expect(screen.queryByText(copy.fr.confidence)).toBeNull();
    expect(screen.queryByText(copy.fr.verify)).toBeNull();
    expect(screen.queryByText(copy.fr.sources)).toBeNull();
  });
});
