import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { copy } from "../../src/ui/src/app/data.js";
import WorkspaceLayout from "../../src/ui/src/components/WorkspaceLayout.jsx";

const appState = vi.hoisted(() => ({
  lang: "fr",
  setLang: vi.fn(),
  user: { role: "lecteur", username: "test-user" },
  error: "",
  setError: vi.fn(),
  webEnabled: false,
  setWebEnabled: vi.fn(),
  webAvailable: true,
  logout: vi.fn(),
}));

vi.mock("../../src/ui/src/app/AppContext.jsx", () => ({
  useApp: () => appState,
}));

vi.mock("../../src/ui/src/api.js", () => ({
  api: {
    conversations: {
      list: vi.fn().mockResolvedValue([
        { conversation_id: "c1", title: "Question enregistrée", updated_at: "2026-11-28T10:00:00Z" },
      ]),
      get: vi.fn(),
      remove: vi.fn(),
    },
  },
}));

function renderWorkspace(role, path = `/${role}/chat`) {
  appState.user = { role, username: `${role}.test` };
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/login" element={<p>{copy.fr.login}</p>} />
        <Route element={<WorkspaceLayout />}>
          <Route path="*" element={<p>Espace de travail</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  appState.lang = "fr";
  appState.error = "";
  appState.webEnabled = false;
  appState.webAvailable = true;
});

afterEach(cleanup);

describe("role-based workspace navigation", () => {
  test.each(["lecteur", "editeur"])("%s sees only their chat and document routes", (role) => {
    renderWorkspace(role);

    expect(screen.getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual([
      `/${role}/chat`,
      `/${role}/documents`,
    ]);
  });

  test.each(["lecteur", "editeur"])("%s keeps the workspace sidebar pinned to the viewport top", (role) => {
    renderWorkspace(role);

    const sidebar = screen.getByRole("navigation").closest("aside");
    expect(sidebar.className).toContain("lg:sticky");
    expect(sidebar.className).toContain("lg:self-start");
  });

  test.each(["lecteur", "editeur"])("%s finds the saved conversations under Conversation, on every page", async (role) => {
    const user = userEvent.setup();
    renderWorkspace(role, `/${role}/documents`);

    const navigation = screen.getByRole("navigation");
    expect(await within(navigation).findByText("Question enregistrée")).toBeTruthy();

    await user.click(within(navigation).getByRole("button", { name: copy.fr.hideHistory }));
    expect(within(navigation).queryByText("Question enregistrée")).toBeNull();
    await user.click(within(navigation).getByRole("button", { name: copy.fr.showHistory }));
    expect(await within(navigation).findByText("Question enregistrée")).toBeTruthy();
  });

  test("admin has no conversation list", () => {
    renderWorkspace("admin", "/admin");

    expect(document.getElementById("conversation-history")).toBeNull();
  });

  test.each(["lecteur", "editeur"])("%s opens the menu from the right in Arabic on a small screen", async (role) => {
    const user = userEvent.setup();
    appState.lang = "ar";
    renderWorkspace(role);

    const sidebar = screen.getByRole("navigation").closest("aside");
    expect(sidebar.className).toContain("translate-x-full");

    await user.click(screen.getAllByRole("button", { name: copy.ar.showNavigation })[0]);
    expect(sidebar.className).not.toContain("translate-x-full");
  });

  test("admin sees the administration routes rather than reader routes", () => {
    renderWorkspace("admin", "/admin");

    expect(screen.getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual([
      "/admin",
      "/admin/users",
      "/admin/requests",
      "/admin/documents",
      "/admin/web",
      "/admin/audit",
    ]);
  });

  test("shows the web-search control only when the API says it is available", async () => {
    const user = userEvent.setup();
    renderWorkspace("lecteur");

    const toggle = screen.getByRole("checkbox", { name: copy.fr.useWeb });
    await user.click(toggle);
    expect(appState.setWebEnabled).toHaveBeenCalledWith(true);

    cleanup();
    appState.webAvailable = false;
    renderWorkspace("editeur");
    expect(screen.queryByRole("checkbox", { name: copy.fr.useWeb })).toBeNull();
  });

  test("does not expose web search to administrators", () => {
    renderWorkspace("admin", "/admin");

    expect(screen.queryByRole("checkbox", { name: copy.fr.useWeb })).toBeNull();
  });

  test("logs out and navigates to the login screen", async () => {
    const user = userEvent.setup();
    renderWorkspace("lecteur");

    await user.click(screen.getByRole("button", { name: copy.fr.signOut }));

    expect(appState.logout).toHaveBeenCalledOnce();
    expect(screen.getByText(copy.fr.login)).toBeTruthy();
  });
});
