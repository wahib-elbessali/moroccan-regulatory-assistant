import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { api, getToken } from "../../src/ui/src/api.js";
import { AppProvider, useApp } from "../../src/ui/src/app/AppContext.jsx";

vi.mock("../../src/ui/src/api.js", () => ({
  api: {
    auth: { me: vi.fn() },
    documents: { list: vi.fn() },
  },
  getToken: vi.fn(),
  saveToken: vi.fn(),
}));

function SessionProbe() {
  const { authLoading, user, webEnabled } = useApp();
  return <div>{authLoading ? "loading" : `${user?.username || "signed-out"}:${webEnabled}`}</div>;
}

beforeEach(() => {
  localStorage.clear();
  getToken.mockReturnValue("session-token");
  api.auth.me.mockResolvedValue({ user_id: "user-1", username: "reader", role: "lecteur", web_available: true });
  api.documents.list.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  localStorage.clear();
});

test("restores the authenticated session after a page reload and preserves the web preference", async () => {
  localStorage.setItem("assistant-web-enabled", "false");
  render(<AppProvider><SessionProbe /></AppProvider>);

  expect(await screen.findByText("reader:false")).toBeTruthy();
  expect(api.auth.me).toHaveBeenCalledOnce();
  expect(api.documents.list).toHaveBeenCalledOnce();
});
