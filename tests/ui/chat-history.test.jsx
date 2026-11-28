import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { api } from "../../src/ui/src/api.js";
import { copy } from "../../src/ui/src/app/data.js";
import { MemoryRouter } from "react-router-dom";
import ConversationHistory, { ConversationProvider } from "../../src/ui/src/components/ConversationHistory.jsx";
import ChatPage from "../../src/ui/src/pages/chat/ChatPage.jsx";

const appState = vi.hoisted(() => ({
  lang: "fr",
  webEnabled: false,
  messages: [],
  setMessages: vi.fn(),
  busy: false,
  setBusy: vi.fn(),
  setError: vi.fn(),
}));

vi.mock("../../src/ui/src/app/AppContext.jsx", () => ({
  useApp: () => appState,
}));

vi.mock("../../src/ui/src/components/ChatView.jsx", () => ({
  default: () => null,
}));

vi.mock("../../src/ui/src/api.js", () => ({
  api: {
    conversations: {
      list: vi.fn(),
      get: vi.fn(),
      remove: vi.fn(),
    },
  },
}));

const conversations = [
  {
    conversation_id: "older",
    title: "Conversation ancienne",
    updated_at: "2025-11-15T10:00:00Z",
  },
  {
    conversation_id: "newer",
    title: "Conversation récente",
    updated_at: "2025-11-16T10:00:00Z",
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  api.conversations.list.mockResolvedValue(conversations);
});

afterEach(cleanup);

// The side-menu list and the chat page share the saved conversations.
function History() {
  return <MemoryRouter><ConversationProvider><ConversationHistory /><ChatPage /></ConversationProvider></MemoryRouter>;
}

describe("conversation history", () => {
  test("keeps long titles inside the menu", async () => {
    render(<History />);

    const title = await screen.findByText("Conversation récente");
    expect(title.className).toContain("truncate");
    expect(title.closest("li").className).toContain("min-w-0");
  });

  test("sorts saved conversations newest first", async () => {
    render(<History />);

    await screen.findByText("Conversation récente");

    const titles = screen.getAllByRole("listitem").map((item) => item.querySelector("button").textContent);
    expect(titles[0]).toContain("Conversation récente");
    expect(titles[1]).toContain("Conversation ancienne");
  });

  test("opens a saved conversation and restores its messages", async () => {
    const answer = { status: "answered", text: "Réponse conservée", citations: [], language: "fr" };
    api.conversations.get.mockResolvedValue({
      conversation_id: "newer",
      messages: [{
        position: 0,
        question: "Question conservée",
        answer,
        available: true,
        language: "fr",
      }],
    });
    const user = userEvent.setup();
    render(<History />);

    await user.click(await screen.findByRole("button", { name: /Conversation récente/ }));

    await waitFor(() => {
      expect(api.conversations.get).toHaveBeenCalledWith("newer");
      expect(appState.setMessages).toHaveBeenCalledWith([{
        id: "newer-0",
        question: "Question conservée",
        answer,
        status: "done",
        language: "fr",
        thinking: null,
        persisted: true,
      }]);
    });
  });

  test("deletes a conversation only after confirmation", async () => {
    api.conversations.remove.mockResolvedValue({});
    const user = userEvent.setup();
    render(<History />);

    await screen.findByText("Conversation récente");
    const olderRow = screen.getByText("Conversation ancienne").closest("li");
    await user.click(within(olderRow).getByRole("button", { name: copy.fr.deleteConversation }));

    expect(api.conversations.remove).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: copy.fr.confirm }));

    await waitFor(() => expect(api.conversations.remove).toHaveBeenCalledWith("older"));
    expect(screen.queryByText("Conversation ancienne")).toBeNull();
    expect(screen.getByText("Conversation récente")).toBeTruthy();
  });

  test("starts a fresh conversation and clears the displayed messages", async () => {
    const user = userEvent.setup();
    render(<History />);

    await user.click(screen.getByRole("button", { name: copy.fr.newConversation }));

    expect(appState.setMessages).toHaveBeenCalledWith([]);
  });
});
