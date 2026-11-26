import axios from "axios";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

export const http = axios.create({
  baseURL: API_BASE,
  timeout: 60_000,
});

http.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

http.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status;
    if (status === 401) {
      saveToken(null);
      window.dispatchEvent(new Event("assistant:unauthorized"));
    }
    const appError = new Error(error.response?.data?.message || error.message || "Service indisponible");
    appError.status = status;
    appError.code = error.response?.data?.code;
    throw appError;
  },
);

export function saveToken(token) {
  if (token) sessionStorage.setItem("assistant-token", token);
  else sessionStorage.removeItem("assistant-token");
}

export function getToken() {
  return sessionStorage.getItem("assistant-token");
}

function parseSse(responseText, state, onEvent, flush = false) {
  state.buffer += responseText.slice(state.readOffset);
  state.readOffset = responseText.length;
  const messages = state.buffer.split(/\r?\n\r?\n/);
  state.buffer = flush ? "" : messages.pop() || "";
  if (flush && messages.at(-1) === "") messages.pop();
  for (const message of messages) {
    const event = message.match(/^event:\s*(.+)$/m)?.[1];
    const data = [...message.matchAll(/^data:\s?(.*)$/gm)].map((match) => match[1]).join("\n");
    if (event && data) onEvent({ event, data: JSON.parse(data) });
  }
}

async function streamAsk(question, useWeb, onEvent) {
  const state = { buffer: "", readOffset: 0 };
  let receivedDone = false;
  const dispatch = (message) => {
    if (message.event === "done") receivedDone = true;
    onEvent(message);
  };
  await http.post("/ask", { question, use_web: useWeb }, {
    responseType: "text",
    timeout: 660_000,
    onDownloadProgress: ({ event }) => {
      const responseText = event?.target?.responseText;
      if (typeof responseText === "string") parseSse(responseText, state, dispatch);
    },
  }).then((response) => parseSse(response.data, state, dispatch, true));
  if (!receivedDone) {
    const error = new Error("The answer stream ended before completion.");
    error.code = "STREAM_INTERRUPTED";
    throw error;
  }
}

async function uploadDocument(file, fields) {
  const form = new FormData();
  form.append("file", file);
  form.append("title", fields.title);
  if (fields.source) form.append("source", fields.source);
  if (fields.date) form.append("date", fields.date);
  for (const role of fields.roles || []) form.append("roles", role);
  const { data } = await http.post("/documents", form);
  return data;
}

export const api = {
  auth: {
    async login(username, password) {
      const { data } = await http.post("/auth/login", { username, password });
      saveToken(data.access_token);
      const profile = await this.me();
      return profile;
    },
    async me() {
      const { data } = await http.get("/auth/me");
      return data;
    },
    async requestAccount(payload) {
      const { data } = await http.post("/auth/account-requests", payload);
      return data;
    },
  },
  ask: streamAsk,
  conversations: {
    async list() {
      const { data } = await http.get("/conversations");
      return data;
    },
    async create() {
      const { data } = await http.post("/conversations", {});
      return data;
    },
    async get(conversationId) {
      const { data } = await http.get(`/conversations/${conversationId}`);
      return data;
    },
    async addMessage(conversationId, question, answer) {
      const { data } = await http.post(`/conversations/${conversationId}/messages`, { question, answer });
      return data;
    },
    async remove(conversationId) {
      await http.delete(`/conversations/${conversationId}`);
    },
  },
  documents: {
    async list() {
      const { data } = await http.get("/documents");
      return data;
    },
    upload: uploadDocument,
    async status(docId) {
      const { data } = await http.get(`/documents/${docId}/status`);
      return data;
    },
    async remove(docId) {
      await http.delete(`/documents/${docId}`);
    },
  },
  admin: {
    async users() {
      const { data } = await http.get("/admin/users");
      return data;
    },
    async roles() {
      const { data } = await http.get("/admin/roles");
      return data;
    },
    async accountRequests() {
      const { data } = await http.get("/admin/account-requests");
      return data;
    },
    async audit() {
      const { data } = await http.get("/admin/audit", { params: { limit: 100 } });
      return data;
    },
    async createUser(payload) {
      const { data } = await http.post("/admin/users", payload);
      return data;
    },
    async updateUserRole(userId, roleId) {
      const { data } = await http.patch(`/admin/users/${userId}/role`, { role_id: roleId });
      return data;
    },
    async setUserActive(userId, isActive) {
      const { data } = await http.patch(`/admin/users/${userId}/active`, { is_active: isActive });
      return data;
    },
    async decideAccountRequest(requestId, decision, roleId) {
      const url = `/admin/account-requests/${requestId}/${decision}`;
      const { data } = decision === "approve"
        ? await http.post(url, { role_id: roleId })
        : await http.post(url);
      return data;
    },
    async setRoleWeb(roleId, enabled) {
      const { data } = await http.patch(`/admin/roles/${roleId}/web`, { web_enabled: enabled });
      return data;
    },
    async setDocumentRoles(docId, roles) {
      const { data } = await http.put(`/admin/documents/${docId}/roles`, { roles });
      return data;
    },
  },
};