function configuredCredentials() {
  const options = [
    ["LIVE_API_USERNAME", "LIVE_API_PASSWORD"],
    ["EDITOR_USERNAME", "EDITOR_PASSWORD"],
    ["READER_USERNAME", "READER_PASSWORD"],
    ["ADMIN_USERNAME", "ADMIN_PASSWORD"],
  ];
  for (const [usernameKey, passwordKey] of options) {
    const username = process.env[usernameKey];
    const password = process.env[passwordKey];
    if (username && password) return { username, password };
  }
  return null;
}

export const credentials = configuredCredentials();
export const liveApiSkipReason = credentials
  ? false
  : "Set LIVE_API_USERNAME/PASSWORD or a role-specific username/password to run against the real API.";
export const apiBaseUrl = (
  process.env.LIVE_API_BASE_URL
  || process.env.API_PROXY_TARGET
  || "http://127.0.0.1:8000"
).replace(/\/+$/, "");

export async function assertResponseStatus(response, expectedStatus, operation) {
  if (response.status !== expectedStatus) {
    const body = await response.text();
    throw new Error(`${operation}: expected HTTP ${expectedStatus}, received ${response.status}${body ? `: ${body}` : ""}`);
  }
}

export async function requestApi(path, { token, method = "GET", body, signal } = {}) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(`${apiBaseUrl}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  return response;
}

export async function loginLiveApi() {
  if (!credentials) throw new Error("Live API credentials are required.");
  const loginResponse = await requestApi("/auth/login", {
    method: "POST",
    body: credentials,
  });
  await assertResponseStatus(loginResponse, 200, "Login");
  const { access_token: token } = await loginResponse.json();
  if (!token) throw new Error("Login response did not contain an access_token.");

  const profileResponse = await requestApi("/auth/me", { token });
  await assertResponseStatus(profileResponse, 200, "Load profile");
  return { token, profile: await profileResponse.json() };
}
