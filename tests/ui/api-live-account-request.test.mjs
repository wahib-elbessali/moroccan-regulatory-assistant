import assert from "node:assert/strict";
import { test } from "node:test";
import {
  assertResponseStatus,
  liveApiSkipReason,
  loginLiveApi,
  requestApi,
} from "./api-live-helpers.mjs";

// Réutilise le nom du compte connecté et vérifie que l'API refuse le doublon sans le créer.
test("rejects an account request for the authenticated user's existing username", {
  skip: liveApiSkipReason,
}, async () => {
  const { profile } = await loginLiveApi();
  const response = await requestApi("/auth/account-requests", {
    method: "POST",
    body: {
      username: profile.username,
      password: "Live-api-conflict-test-password",
      full_name: "P7 live API conflict check",
    },
  });

  await assertResponseStatus(response, 409, "Account request for an existing username");
  const error = await response.json();
  assert.equal(error.code, "conflict");
  assert.match(error.message, /username not available/i);
});
