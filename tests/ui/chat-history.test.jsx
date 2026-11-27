import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { api } from "../../src/ui/src/api.js";
import { copy } from "../../src/ui/src/app/data.js";
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

describe("conversation history", () => {
  test("keeps the conversation history independently pinned while chat content grows", async () => {
    render(<ChatPage />);

    await screen.findByText("Conversation récente");

    const sidebar = document.getElementById("conversation-history");
    expect(sidebar.className).toContain("md:sticky");
    expect(sidebar.className).toContain("md:self-start");
    expect(sidebar.className).toContain("md:h-[calc(100vh-68px)]");
  });

  test("can hide and restore the conversation history panel", async () => {
    const user = userEvent.setup();
    render(<ChatPage />);

    await screen.findByText("Conversation récente");
    await user.click(screen.getByRole("button", { name: copy.fr.hideHistory }));
    expect(screen.queryByText("Conversation récente")).toBeNull();

    await user.click(screen.getByRole("button", { name: copy.fr.showHistory }));
    expect(await screen.findByText("Conversation récente")).toBeTruthy();
  });

  test("sorts saved conversations newest first", async () => {
    render(<ChatPage />);

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
    render(<ChatPage />);

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
    render(<ChatPage />);

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
    render(<ChatPage />);

    await user.click(screen.getByRole("button", { name: copy.fr.newConversation }));

    expect(appState.setMessages).toHaveBeenCalledWith([]);
  });
});
