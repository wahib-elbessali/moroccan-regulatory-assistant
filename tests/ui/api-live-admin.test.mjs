import assert from "node:assert/strict";
import { test } from "node:test";
import {
  assertResponseStatus,
  liveApiSkipReason,
  loginLiveApi,
  requestApi,
} from "./api-live-helpers.mjs";

// Avec un compte admin, vérifie que les principales collections d'administration répondent.
test("reads the real admin API collections", {
  skip: liveApiSkipReason,
}, async (context) => {
  const { token, profile } = await loginLiveApi();
  if (profile.role !== "admin") {
    context.skip("Use ADMIN_USERNAME and ADMIN_PASSWORD to test admin API routes.");
    return;
  }

  const collections = [
    ["/admin/users", "users"],
    ["/admin/roles", "roles"],
    ["/admin/account-requests", "account requests"],
    ["/admin/audit?limit=100", "audit log"],
  ];

  for (const [path, name] of collections) {
    const response = await requestApi(path, { token });
    await assertResponseStatus(response, 200, `Read admin ${name}`);
    assert.ok(Array.isArray(await response.json()), `Admin ${name} response must be an array.`);
  }
});
