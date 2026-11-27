import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../../src/ui/src/api.js";
import { copy } from "../../src/ui/src/app/data.js";
import DocumentsPage from "../../src/ui/src/pages/documents/DocumentsPage.jsx";

const appState = vi.hoisted(() => ({ docs: [] }));

vi.mock("../../src/ui/src/app/AppContext.jsx", async () => {
  const React = await import("react");
  return {
    useApp: () => {
      const [docs, setDocs] = React.useState(appState.docs);
      return { lang: "fr", docs, setDocs };
    },
  };
});

vi.mock("../../src/ui/src/api.js", () => ({
  api: {
    documents: { upload: vi.fn(), status: vi.fn(), remove: vi.fn() },
    admin: { setDocumentRoles: vi.fn() },
  },
}));

vi.mock("../../src/ui/src/app/data.js", async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, pause: vi.fn().mockResolvedValue(undefined) };
});

import { pause } from "../../src/ui/src/app/data.js";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  appState.docs = [];
});

test("shows a clear text label for document deletion", () => {
  appState.docs = [{
    doc_id: "reader-doc",
    title: "Document du lecteur",
    source_file: "document.pdf",
    status: "ready",
    is_mine: true,
    roles: [],
  }];
  render(<DocumentsPage role="lecteur" />);

  expect(screen.getByRole("button", { name: copy.fr.delete })).toBeTruthy();
});

async function openUploadForm(role) {
  const user = userEvent.setup();
  const { container } = render(<DocumentsPage role={role} />);
  await user.click(screen.getByRole("button", { name: copy.fr.upload }));
  await user.type(screen.getByLabelText(copy.fr.title), "Document test");
  await user.upload(container.querySelector('input[type="file"]'), new File(["PDF"], "test.pdf", { type: "application/pdf" }));
  return { user, container };
}

test("a reader uploads privately without a roles form field", async () => {
  api.documents.upload.mockResolvedValue({ doc_id: "doc-private", status: "ready" });
  const { container } = await openUploadForm("lecteur");
  expect(screen.getByText(copy.fr.private)).toBeTruthy();

  fireEvent.submit(container.querySelector("form"));

  await waitFor(() => {
    expect(api.documents.upload).toHaveBeenCalledWith(
      expect.any(File),
      expect.objectContaining({ title: "Document test", roles: [] }),
    );
  });
});

test("an editor must choose visibility before the upload API is called", async () => {
  const { container } = await openUploadForm("editeur");
  fireEvent.submit(container.querySelector("form"));

  expect((await screen.findByRole("alert")).textContent).toBe("Choisissez une visibilité.");
  expect(api.documents.upload).not.toHaveBeenCalled();
});

test.each([
  ["public", ["lecteur", "editeur"]],
  ["internal", ["editeur"]],
])("an editor uploads a %s document with the matching API roles", async (visibility, roles) => {
  api.documents.upload.mockResolvedValue({ doc_id: "editor-doc", status: "ready" });
  const { user, container } = await openUploadForm("editeur");

  await user.click(screen.getByLabelText(copy.fr[visibility]));
  fireEvent.submit(container.querySelector("form"));

  await waitFor(() => {
    expect(api.documents.upload).toHaveBeenCalledWith(
      expect.any(File),
      expect.objectContaining({ title: "Document test", roles }),
    );
  });
  expect(screen.queryByRole("alert")).toBeNull();
});

test("polls until an uploaded document reaches a terminal status", async () => {
  api.documents.upload.mockResolvedValue({ doc_id: "processing-doc", status: "received" });
  api.documents.status
    .mockResolvedValueOnce({ status: "extracting" })
    .mockResolvedValueOnce({ status: "chunked" })
    .mockResolvedValueOnce({ status: "indexed" })
    .mockResolvedValueOnce({ status: "ready" });
  const { container } = await openUploadForm("lecteur");

  fireEvent.submit(container.querySelector("form"));

  await waitFor(() => expect(api.documents.status).toHaveBeenCalledTimes(4));
  expect(api.documents.status).toHaveBeenNthCalledWith(1, "processing-doc");
  expect(api.documents.status).toHaveBeenNthCalledWith(4, "processing-doc");
  expect(pause).toHaveBeenCalledTimes(4);
  expect(pause).toHaveBeenCalledWith(2000);
});

test("shows duplicate matches returned by the document status API", async () => {
  api.documents.upload.mockResolvedValue({ doc_id: "duplicate-doc", status: "received" });
  api.documents.status.mockResolvedValue({
    status: "ready",
    duplicate_of: ["existing-doc"],
  });
  const { container } = await openUploadForm("lecteur");

  fireEvent.submit(container.querySelector("form"));

  expect(await screen.findByText(copy.fr.duplicate)).toBeTruthy();
  expect(screen.getByRole("link", { name: "existing-doc" }).getAttribute("href")).toBe("#existing-doc");
});

test("surfaces upload API failures instead of treating them as successful", async () => {
  api.documents.upload.mockRejectedValue(new Error("Upload failed"));
  const { container } = await openUploadForm("lecteur");

  fireEvent.submit(container.querySelector("form"));

  expect((await screen.findByRole("alert")).textContent).toContain("Upload failed");
});
