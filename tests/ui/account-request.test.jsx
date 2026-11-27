import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { copy } from "../../src/ui/src/app/data.js";

vi.mock("../../src/ui/src/app/AppContext.jsx", () => ({
  useApp: () => ({
    lang: "ar",
    setLang: vi.fn(),
    setError: vi.fn(),
  }),
}));

vi.mock("../../src/ui/src/api.js", () => ({
  api: {
    auth: {
      requestAccount: vi.fn(),
    },
  },
}));

import { api } from "../../src/ui/src/api.js";
import { AccountRequestPage, LoginPage } from "../../src/ui/src/pages/auth/AuthPages.jsx";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

test("the login page has no local demo-role shortcuts", () => {
  render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>,
  );

  expect(screen.getByRole("button", { name: copy.ar.signIn })).toBeTruthy();
  expect(screen.queryByRole("button", { name: copy.ar.lecteur })).toBeNull();
  expect(screen.queryByRole("button", { name: copy.ar.editeur })).toBeNull();
  expect(screen.queryByRole("button", { name: copy.ar.admin })).toBeNull();
});

describe("T18 - account request 429", () => {
  test("shows the waiting-requests message after submitting", async () => {
    const error = new Error("Too many requests");
    error.status = 429;
    api.auth.requestAccount.mockRejectedValue(error);

    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AccountRequestPage />
      </MemoryRouter>,
    );

    await user.type(screen.getByLabelText("اسم المستخدم"), "new-user");
    await user.type(screen.getByLabelText("الاسم الكامل"), "مستخدم جديد");
    await user.type(screen.getByLabelText("كلمة المرور"), "secure-pass-123");
    await user.type(screen.getByLabelText("تأكيد كلمة المرور"), "secure-pass-123");
    await user.click(screen.getByRole("button", { name: "إرسال الطلب" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("طلبات كثيرة قيد الانتظار. حاول لاحقًا.");
  });

  test("rejects mismatched passwords without sending the request", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AccountRequestPage />
      </MemoryRouter>,
    );

    await user.type(screen.getByLabelText("اسم المستخدم"), "new-user");
    await user.type(screen.getByLabelText("الاسم الكامل"), "مستخدم جديد");
    await user.type(screen.getByLabelText("كلمة المرور"), "secure-pass-123");
    await user.type(screen.getByLabelText("تأكيد كلمة المرور"), "different-pass");
    await user.click(screen.getByRole("button", { name: "إرسال الطلب" }));

    expect((await screen.findByRole("alert")).textContent).toBe("كلمتا المرور غير متطابقتين.");
    expect(api.auth.requestAccount).not.toHaveBeenCalled();
  });
});

describe("account request contract", () => {
  test("submits the account fields and confirms a successful request", async () => {
    api.auth.requestAccount.mockResolvedValue({ request_id: "request-1", status: "pending" });
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AccountRequestPage />
      </MemoryRouter>,
    );

    await user.type(screen.getByLabelText(copy.ar.username), "new.reader");
    await user.type(screen.getByLabelText(copy.ar.fullName), "قارئ جديد");
    await user.type(screen.getByLabelText(copy.ar.password), "secure-pass-123");
    await user.type(screen.getByLabelText(copy.ar.repeatPassword), "secure-pass-123");
    await user.click(screen.getByRole("button", { name: copy.ar.sendRequest }));

    expect((await screen.findByRole("status")).textContent).toContain(copy.ar.requestSent);
    expect(api.auth.requestAccount).toHaveBeenCalledWith({
      username: "new.reader",
      password: "secure-pass-123",
      full_name: "قارئ جديد",
    });
  });

  test("shows the username-unavailable message after a 409", async () => {
    const error = new Error("Conflict");
    error.status = 409;
    api.auth.requestAccount.mockRejectedValue(error);
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AccountRequestPage />
      </MemoryRouter>,
    );

    await user.type(screen.getByLabelText(copy.ar.username), "existing.user");
    await user.type(screen.getByLabelText(copy.ar.fullName), "مستخدم موجود");
    await user.type(screen.getByLabelText(copy.ar.password), "secure-pass-123");
    await user.type(screen.getByLabelText(copy.ar.repeatPassword), "secure-pass-123");
    await user.click(screen.getByRole("button", { name: copy.ar.sendRequest }));

    expect((await screen.findByRole("alert")).textContent).toContain(copy.ar.usernameUnavailable);
  });

  test("refuses a password shorter than the configured minimum", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <MemoryRouter>
        <AccountRequestPage />
      </MemoryRouter>,
    );

    await user.type(screen.getByLabelText(copy.ar.username), "short.password");
    await user.type(screen.getByLabelText(copy.ar.fullName), "مستخدم");
    await user.type(screen.getByLabelText(copy.ar.password), "short");
    await user.type(screen.getByLabelText(copy.ar.repeatPassword), "short");
    fireEvent.submit(container.querySelector("form"));

    expect((await screen.findByRole("alert")).textContent).toContain(
      copy.ar.passwordShort.replace("{min}", "8"),
    );
    expect(api.auth.requestAccount).not.toHaveBeenCalled();
  });
});
