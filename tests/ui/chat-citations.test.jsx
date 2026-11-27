import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { api } from "../../src/ui/src/api.js";
import { copy } from "../../src/ui/src/app/data.js";
import ChatView from "../../src/ui/src/components/ChatView.jsx";

vi.mock("../../src/ui/src/api.js", () => ({
  api: {
    ask: vi.fn(),
    conversations: { create: vi.fn(), addMessage: vi.fn() },
  },
}));

function renderAnswer(answer) {
  const messages = [{
    id: "answer-1",
    question: "Question test",
    answer,
    status: "done",
    thinking: null,
  }];
  return render(
    <ChatView
      lang="fr"
      t={copy.fr}
      webEnabled={false}
      messages={messages}
      setMessages={vi.fn()}
      busy={false}
      setBusy={vi.fn()}
      conversationId="conversation-1"
      onConversationCreated={vi.fn()}
      onMessageSaved={vi.fn()}
      onPersistenceError={vi.fn()}
    />,
  );
}

function citation(overrides = {}) {
  return {
    title: "Loi test",
    excerpt: "Extrait cité",
    article: "Article 1",
    page: 4,
    source: "Bulletin officiel",
    url: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  HTMLElement.prototype.scrollIntoView = vi.fn();
});

afterEach(cleanup);

describe("citation rendering and safety", () => {
  test("opens the matching citation from an inline marker", async () => {
    const user = userEvent.setup();
    renderAnswer({
      status: "answered",
      text: "Réponse fondée [1].",
      citations: [citation()],
      confidence: 0.9,
      language: "fr",
    });

    HTMLElement.prototype.scrollIntoView.mockClear();
    await user.click(screen.getByRole("button", { name: "[1]" }));

    expect(screen.getByRole("heading", { name: "Loi test" })).toBeTruthy();
    expect(screen.getByText("Extrait cité")).toBeTruthy();
    expect(screen.getByText("Réponse générée, vérifiez les sources")).toBeTruthy();
    expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalledWith({
      behavior: "smooth",
      block: "nearest",
    });
  });

  test("renders untrusted answer text as text rather than HTML", () => {
    const payload = '<img src=x onerror="alert(1)">';
    const { container } = renderAnswer({
      status: "answered",
      text: payload,
      citations: [],
      confidence: 0.5,
      language: "fr",
    });

    expect(screen.getByText(payload)).toBeTruthy();
    expect(container.querySelector("img")).toBeNull();
  });

  test("does not turn a javascript citation URL into a link", async () => {
    const user = userEvent.setup();
    renderAnswer({
      status: "answered",
      text: "Réponse [1].",
      citations: [citation({ url: "javascript:alert(1)" })],
      confidence: 0.9,
      language: "fr",
    });

    await user.click(screen.getByRole("button", { name: "[1]" }));

    expect(screen.getByText("Extrait cité")).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });

  test("marks a web-only response and uses a safe external citation link", async () => {
    const user = userEvent.setup();
    renderAnswer({
      status: "answered",
      text: "WEB_ONLY\nRéponse web [1].",
      citations: [citation({ url: "https://example.test/source" })],
      confidence: 0.8,
      language: "fr",
    });

    expect(screen.getByText("WEB_ONLY")).toBeTruthy();
    expect(screen.getByText("Réponse web", { exact: false })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "[1]" }));

    const link = screen.getByRole("link");
    expect(link.getAttribute("href")).toBe("https://example.test/source");
    expect(link.textContent).toContain("https://example.test/source");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
  });

  test("keeps a citation without a URL as a non-link source", async () => {
    const user = userEvent.setup();
    renderAnswer({
      status: "answered",
      text: "Réponse [1].",
      citations: [citation()],
      confidence: 0.7,
      language: "fr",
    });

    await user.click(screen.getByRole("button", { name: "[1]" }));

    expect(screen.getByText("Extrait cité")).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });
});
