import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { test } from "node:test";
import {
  apiBaseUrl,
  assertResponseStatus,
  liveApiSkipReason,
  loginLiveApi,
} from "./api-live-helpers.mjs";
const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

// Envoie un fichier unique, attend la fin de son traitement, puis le supprime.
test("uploads, polls, and removes a document through the live API", {
  skip: liveApiSkipReason,
}, async () => {
  let token;
  let docId;
  let latestStatus;

  try {
    const session = await loginLiveApi();
    token = session.token;
    assert.ok(["admin", "editeur", "lecteur"].includes(session.profile.role));
    const headers = { Authorization: `Bearer ${token}` };

    // Le nom unique évite les conflits; l'éditeur doit préciser les rôles du document.
    const uniqueId = randomUUID();
    const form = new FormData();
    form.append("file", new Blob([`Live API upload test ${uniqueId}`], { type: "text/plain" }), `p7-upload-${uniqueId}.txt`);
    form.append("title", `P7 live upload test ${uniqueId}`);
    if (session.profile.role === "editeur") {
      form.append("roles", "lecteur");
      form.append("roles", "editeur");
    }

    const uploadResponse = await fetch(`${apiBaseUrl}/documents`, {
      method: "POST",
      headers,
      body: form,
    });
    await assertResponseStatus(uploadResponse, 202, "Upload document");
    const upload = await uploadResponse.json();
    docId = upload.doc_id;
    assert.ok(docId, "Upload response did not contain a doc_id.");

    // Interroge le statut jusqu'à ce que le traitement soit terminé ou que le délai soit écoulé.
    for (let attempt = 0; attempt < 60; attempt += 1) {
      await delay(2000);
      const statusResponse = await fetch(`${apiBaseUrl}/documents/${encodeURIComponent(docId)}/status`, { headers });
      await assertResponseStatus(statusResponse, 200, "Read document status");
      latestStatus = (await statusResponse.json()).status;
      if (latestStatus === "ready" || latestStatus === "failed") break;
    }

    assert.equal(latestStatus, "ready", `Document processing ended with status "${latestStatus || "unknown"}".`);
  } finally {
    if (token && docId) {
      const headers = { Authorization: `Bearer ${token}` };
      // N'essaie de supprimer le fichier qu'une fois le traitement terminé.
      if (latestStatus !== "ready" && latestStatus !== "failed") {
        const statusResponse = await fetch(`${apiBaseUrl}/documents/${encodeURIComponent(docId)}/status`, { headers });
        await assertResponseStatus(statusResponse, 200, "Check document before cleanup");
        latestStatus = (await statusResponse.json()).status;
      }

      assert.ok(
        latestStatus === "ready" || latestStatus === "failed",
        `Test document ${docId} is still processing; remove it after processing finishes.`,
      );
      const deleteResponse = await fetch(`${apiBaseUrl}/documents/${encodeURIComponent(docId)}`, {
        method: "DELETE",
        headers,
      });
      await assertResponseStatus(deleteResponse, 204, "Remove test document");
    }
  }
});
