import { afterEach, expect, test, vi } from "vitest";
import { api, http } from "../../src/ui/src/api.js";

afterEach(() => vi.restoreAllMocks());

test("parses events split across download chunks and requires done", async () => {
  const firstChunk = 'event: thinking\ndata: {"text":"Recherche"}\n\nevent:';
  const fullResponse = `${firstChunk} done\ndata: {}\n\n`;
  const post = vi.spyOn(http, "post").mockImplementation(async (_url, _body, config) => {
    config.onDownloadProgress({ event: { target: { responseText: firstChunk } } });
    config.onDownloadProgress({ event: { target: { responseText: fullResponse } } });
    return { data: fullResponse };
  });
  const events = [];

  await api.ask("Question", false, (message) => events.push(message));
  expect(events).toEqual([
    { event: "thinking", data: { text: "Recherche" } },
    { event: "done", data: {} },
  ]);
  expect(post).toHaveBeenCalledWith(
    "/ask",
    { question: "Question", use_web: false },
    expect.objectContaining({
      responseType: "text",
      timeout: 660_000,
      onDownloadProgress: expect.any(Function),
    }),
  );
});

test("reports a stream that ends without a done event", async () => {
  vi.spyOn(http, "post").mockResolvedValue({ data: 'event: thinking\ndata: {"text":"Recherche"}\n\n' });

  await expect(api.ask("Question", false, vi.fn())).rejects.toMatchObject({ code: "STREAM_INTERRUPTED" });
});
