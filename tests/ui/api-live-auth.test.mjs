import assert from "node:assert/strict";
import { test } from "node:test";
import { liveApiSkipReason, loginLiveApi } from "./api-live-helpers.mjs";

// Vérifie que les identifiants réels ouvrent une session et renvoient un profil complet.
test("authenticates against the real API and loads the user's profile", {
  skip: liveApiSkipReason,
}, async () => {
  const { token, profile } = await loginLiveApi();

  assert.ok(token);
  assert.ok(profile.user_id);
  assert.ok(profile.username);
  assert.ok(["admin", "editeur", "lecteur"].includes(profile.role));
  assert.equal(typeof profile.web_available, "boolean");
});
