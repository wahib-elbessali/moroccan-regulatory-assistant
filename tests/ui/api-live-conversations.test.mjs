import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { test } from "node:test";
import {
  assertResponseStatus,
  liveApiSkipReason,
  loginLiveApi,
  requestApi,
} from "./api-live-helpers.mjs";

// Vérifie le cycle complet d'une conversation, puis supprime les données créées par le test.
test("creates, lists, stores, reads, and deletes a conversation through the real API", {
  skip: liveApiSkipReason,
}, async (context) => {
  const { token, profile } = await loginLiveApi();
  if (profile.role === "admin") {
    context.skip("Use reader or editor credentials to test the P7 conversation screen.");
    return;
  }

  let conversationId;
  try {
    // Crée une conversation avec un titre unique pour éviter les collisions.
    const createResponse = await requestApi("/conversations", {
      token,
      method: "POST",
      body: { title: `P7 live API test ${randomUUID()}` },
    });
    await assertResponseStatus(createResponse, 201, "Create conversation");
    const created = await createResponse.json();
    conversationId = created.conversation_id;
    assert.ok(conversationId);

    // Confirme qu'elle apparaît dans l'historique du compte connecté.
    const listResponse = await requestApi("/conversations", { token });
    await assertResponseStatus(listResponse, 200, "List conversations");
    assert.ok((await listResponse.json()).some((item) => item.conversation_id === conversationId));

    // Enregistre une paire question-réponse et vérifie qu'elle est relue intacte.
    const answer = {
      status: "answered",
      text: "Réponse de test enregistrée par l'API.",
      citations: [],
      confidence: 0.5,
      language: "fr",
    };
    const appendResponse = await requestApi(`/conversations/${conversationId}/messages`, {
      token,
      method: "POST",
      body: { question: `Question P7 ${randomUUID()}`, answer },
    });
    await assertResponseStatus(appendResponse, 201, "Save conversation message");
    assert.equal((await appendResponse.json()).position, 1);

    const detailResponse = await requestApi(`/conversations/${conversationId}`, { token });
    await assertResponseStatus(detailResponse, 200, "Read conversation");
    const detail = await detailResponse.json();
    assert.equal(detail.messages.length, 1);
    assert.deepEqual(detail.messages[0].answer, answer);
  } finally {
    if (conversationId) {
      // Nettoie la conversation même si une assertion précédente échoue.
      const deleteResponse = await requestApi(`/conversations/${conversationId}`, {
        token,
        method: "DELETE",
      });
      await assertResponseStatus(deleteResponse, 204, "Delete test conversation");
    }
  }
});
