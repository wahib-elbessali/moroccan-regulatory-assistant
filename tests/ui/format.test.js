import { expect, test } from "vitest";
import { sourceLabel } from "../../src/ui/src/components/ChatView.jsx";
import { isValidDate } from "../../src/ui/src/pages/documents/DocumentsPage.jsx";

test("a web source is shown by its site name", () => {
  expect(sourceLabel("https://adala.justice.gov.ma/resources/%D8%B8%D9%87.pdf")).toBe("adala.justice.gov.ma");
  expect(sourceLabel("http://www.sgg.gov.ma/BO/7412.pdf")).toBe("sgg.gov.ma");
});

test("a source that is not a web address is shown as it is", () => {
  expect(sourceLabel("Commune de Tamesna")).toBe("Commune de Tamesna");
  expect(sourceLabel(undefined)).toBe(undefined);
});

test("only real calendar dates written YYYY-MM-DD are accepted", () => {
  expect(isValidDate("2025-03-12")).toBe(true);
  expect(isValidDate("2024-02-29")).toBe(true);
  expect(isValidDate("2026-28-11")).toBe(false);
  expect(isValidDate("2026-02-30")).toBe(false);
  expect(isValidDate("12/03/2025")).toBe(false);
});
