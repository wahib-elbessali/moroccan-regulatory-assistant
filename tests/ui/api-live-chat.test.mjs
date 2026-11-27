import assert from "node:assert/strict";
import { test } from "node:test";
import {
  assertResponseStatus,
  liveApiSkipReason,
  loginLiveApi,
  requestApi,
} from "./api-live-helpers.mjs";

// Envoie une question réelle et vérifie que le flux SSE se termine avec un événement terminal.
test("sends a question to the real API and receives a completed SSE stream", {
  skip: liveApiSkipReason,
}, async (context) => {
  const { token, profile } = await loginLiveApi();
  if (profile.role === "admin") {
    context.skip("The P7 admin role does not have a chat screen; use reader or editor credentials.");
    return;
  }

  const response = await requestApi("/ask", {
    token,
    method: "POST",
    body: {
      question: "Quel est le rôle d'un texte réglementaire ?",
      use_web: false,
    },
    signal: AbortSignal.timeout(120_000),
  });
  await assertResponseStatus(response, 200, "Ask question");
  assert.match(response.headers.get("content-type") || "", /text\/event-stream/i);

  const stream = await response.text();
  const events = [...stream.matchAll(/^event:\s*(.+)$/gm)].map((match) => match[1].trim());
  assert.ok(events.includes("done"), "SSE stream did not contain a done event.");
  assert.ok(events.includes("answer") || events.includes("error"), "SSE stream contained neither answer nor error.");
});
