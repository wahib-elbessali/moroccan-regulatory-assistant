export function emptyThinking() {
  return { lines: [], current: "" };
}

export function appendThinkingFragment(thinking, fragment) {
  const lines = [...thinking.lines];
  let current = thinking.current;
  const parts = fragment.split("\n");

  for (let index = 0; index < parts.length; index += 1) {
    current += parts[index];
    if (index < parts.length - 1) {
      lines.push(current);
      current = "";
    }
  }

  return { lines, current };
}