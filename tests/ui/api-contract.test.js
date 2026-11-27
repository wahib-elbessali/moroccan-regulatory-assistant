import { afterEach, expect, test, vi } from "vitest";
import { api, getToken, http, saveToken } from "../../src/ui/src/api.js";

afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
  localStorage.clear();
});

test("auth and conversation calls use the shared HTTP contracts", async () => {
  const profile = { user_id: "user-1", username: "reader", role: "lecteur", web_available: true };
  const post = vi.spyOn(http, "post").mockResolvedValue({ data: { access_token: "session-token" } });
  const get = vi.spyOn(http, "get").mockImplementation(async (path) => ({
    data: path === "/auth/me" ? profile : [],
  }));
  const deletion = vi.spyOn(http, "delete").mockResolvedValue({ data: undefined });
  const conversation = { conversation_id: "conversation-1" };
  post.mockImplementation(async (path) => ({
    data: path === "/auth/login" ? { access_token: "session-token" }
      : path === "/conversations" ? conversation
        : {},
  }));

  await expect(api.auth.login("reader", "password")).resolves.toEqual(profile);
  expect(getToken()).toBe("session-token");
  expect(localStorage.getItem("assistant-token")).toBeNull();
  expect(post).toHaveBeenNthCalledWith(1, "/auth/login", { username: "reader", password: "password" });
  expect(get).toHaveBeenCalledWith("/auth/me");

  const request = { username: "new.reader", password: "password", full_name: "New Reader" };
  await api.auth.requestAccount(request);
  expect(post).toHaveBeenNthCalledWith(2, "/auth/account-requests", request);

  await api.conversations.list();
  await api.conversations.create();
  await api.conversations.get("conversation-1");
  const answer = { status: "answered", text: "Answer", citations: [], confidence: 0.8, language: "fr" };
  await api.conversations.addMessage("conversation-1", "Question", answer);
  await api.conversations.remove("conversation-1");
  expect(get).toHaveBeenCalledWith("/conversations");
  expect(get).toHaveBeenCalledWith("/conversations/conversation-1");
  expect(post).toHaveBeenNthCalledWith(3, "/conversations", {});
  expect(post).toHaveBeenNthCalledWith(4, "/conversations/conversation-1/messages", { question: "Question", answer });
  expect(deletion).toHaveBeenCalledWith("/conversations/conversation-1");
});

test("document uploads use multipart fields and repeated role entries", async () => {
  const post = vi.spyOn(http, "post").mockResolvedValue({ data: { doc_id: "doc-1", status: "received" } });
  const get = vi.spyOn(http, "get").mockResolvedValue({ data: [] });
  const deletion = vi.spyOn(http, "delete").mockResolvedValue({ data: undefined });
  const file = new File(["PDF"], "law.pdf", { type: "application/pdf" });

  await api.documents.upload(file, {
    title: "Law",
    source: "Official journal",
    date: "2026-11-24",
    roles: ["lecteur", "editeur"],
  });
  const form = post.mock.calls[0][1];
  expect(form).toBeInstanceOf(FormData);
  expect(form.get("file")).toBe(file);
  expect(form.get("title")).toBe("Law");
  expect(form.get("source")).toBe("Official journal");
  expect(form.get("date")).toBe("2026-11-24");
  expect(form.getAll("roles")).toEqual(["lecteur", "editeur"]);
  expect(post).toHaveBeenCalledWith("/documents", form);

  await api.documents.list();
  await api.documents.status("doc-1");
  await api.documents.remove("doc-1");
  expect(get).toHaveBeenCalledWith("/documents");
  expect(get).toHaveBeenCalledWith("/documents/doc-1/status");
  expect(deletion).toHaveBeenCalledWith("/documents/doc-1");
});

test("admin calls use the shared routes, query parameters, and request bodies", async () => {
  const get = vi.spyOn(http, "get").mockResolvedValue({ data: [] });
  const post = vi.spyOn(http, "post").mockResolvedValue({ data: {} });
  const patch = vi.spyOn(http, "patch").mockResolvedValue({ data: {} });
  const put = vi.spyOn(http, "put").mockResolvedValue({ data: {} });

  await api.admin.users();
  await api.admin.roles();
  await api.admin.accountRequests();
  await api.admin.audit();
  await api.admin.createUser({ username: "new", role_id: 3 });
  await api.admin.updateUserRole("user-1", 3);
  await api.admin.setUserActive("user-1", false);
  await api.admin.decideAccountRequest("request-1", "approve", 3);
  await api.admin.decideAccountRequest("request-2", "reject");
  await api.admin.setRoleWeb(3, false);
  await api.admin.setDocumentRoles("doc-1", ["editeur"]);

  expect(get).toHaveBeenCalledWith("/admin/users");
  expect(get).toHaveBeenCalledWith("/admin/roles");
  expect(get).toHaveBeenCalledWith("/admin/account-requests");
  expect(get).toHaveBeenCalledWith("/admin/audit", { params: { limit: 100 } });
  expect(post).toHaveBeenCalledWith("/admin/users", { username: "new", role_id: 3 });
  expect(patch).toHaveBeenCalledWith("/admin/users/user-1/role", { role_id: 3 });
  expect(patch).toHaveBeenCalledWith("/admin/users/user-1/active", { is_active: false });
  expect(post).toHaveBeenCalledWith("/admin/account-requests/request-1/approve", { role_id: 3 });
  expect(post).toHaveBeenCalledWith("/admin/account-requests/request-2/reject");
  expect(patch).toHaveBeenCalledWith("/admin/roles/3/web", { web_enabled: false });
  expect(put).toHaveBeenCalledWith("/admin/documents/doc-1/roles", { roles: ["editeur"] });
});

test("the HTTP client attaches the bearer token and clears it after a 401", async () => {
  saveToken("session-token");
  const requestInterceptor = http.interceptors.request.handlers.find((handler) => handler.fulfilled);
  const config = requestInterceptor.fulfilled({ headers: {} });
  expect(config.headers.Authorization).toBe("Bearer session-token");

  const unauthorized = vi.fn();
  window.addEventListener("assistant:unauthorized", unauthorized);
  const responseInterceptor = http.interceptors.response.handlers.find((handler) => handler.rejected);
  let appError;
  try {
    responseInterceptor.rejected({ response: { status: 401, data: { message: "Expired" } } });
  } catch (reason) {
    appError = reason;
  }
  expect(appError).toMatchObject({ status: 401, message: "Expired" });
  expect(getToken()).toBeNull();
  expect(unauthorized).toHaveBeenCalledOnce();
  window.removeEventListener("assistant:unauthorized", unauthorized);
});
