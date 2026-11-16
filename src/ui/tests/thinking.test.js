import assert from "node:assert/strict";
import test from "node:test";
import { appendThinkingFragment, emptyThinking } from "../src/app/thinking.js";

test("appends streaming fragments to the current thinking line", () => {
  let thinking = emptyThinking();
  thinking = appendThinkingFragment(thinking, "Searching ");
  thinking = appendThinkingFragment(thinking, "the corpus");

  assert.deepEqual(thinking, { lines: [], current: "Searching the corpus" });
});

test("starts a new thinking line only when a newline fragment arrives", () => {
  let thinking = emptyThinking();
  thinking = appendThinkingFragment(thinking, "First step");
  thinking = appendThinkingFragment(thinking, "\n");
  thinking = appendThinkingFragment(thinking, "Second");
  thinking = appendThinkingFragment(thinking, " part");

  assert.deepEqual(thinking, { lines: ["First step"], current: "Second part" });
});

test("handles multiple newline separators in one fragment", () => {
  const thinking = appendThinkingFragment(emptyThinking(), "First\nSecond\n");

  assert.deepEqual(thinking, { lines: ["First", "Second"], current: "" });
});