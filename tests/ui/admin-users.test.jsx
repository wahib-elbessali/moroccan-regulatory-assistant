import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { api } from "../../src/ui/src/api.js";
import { copy } from "../../src/ui/src/app/data.js";
import { AdminAuditPage, AdminDataProvider, AdminRequestsPage, AdminUsersPage, AdminWebPage } from "../../src/ui/src/pages/admin/AdminRoutes.jsx";

const { setDocs, setError } = vi.hoisted(() => ({ setDocs: vi.fn(), setError: vi.fn() }));

vi.mock("../../src/ui/src/app/AppContext.jsx", () => ({
  useApp: () => ({ lang: "fr", docs: [], setDocs, setError }),
}));

vi.mock("../../src/ui/src/api.js", () => ({
  api: {
    admin: {
      users: vi.fn().mockResolvedValue([]),
      roles: vi.fn().mockResolvedValue([
        { role_id: 1, name: "admin", web_enabled: true },
        { role_id: 2, name: "editeur", web_enabled: true },
        { role_id: 3, name: "lecteur", web_enabled: true },
      ]),
      accountRequests: vi.fn().mockResolvedValue([]),
      audit: vi.fn().mockResolvedValue([]),
      createUser: vi.fn(),
      decideAccountRequest: vi.fn(),
      updateUserRole: vi.fn().mockResolvedValue({}),
      setUserActive: vi.fn().mockResolvedValue({}),
      setRoleWeb: vi.fn(),
    },
    documents: { list: vi.fn().mockResolvedValue([]) },
  },
}));

function NavigateToUsers() {
  const navigate = useNavigate();
  return <button onClick={() => navigate("/users")}>Aller aux utilisateurs</button>;
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

test("admin user creation uses the API response identity without retaining the password", async () => {
  const createdUser = {
    user_id: "server-user-id",
    username: "new.user",
    full_name: "New User",
    role: "lecteur",
    is_active: true,
    created_at: "2026-11-24T10:00:00Z",
  };
  api.admin.createUser.mockResolvedValue(createdUser);
  api.admin.updateUserRole.mockResolvedValue({ ...createdUser, role: "editeur" });
  const user = userEvent.setup();
  render(
    <MemoryRouter>
      <Routes>
        <Route element={<AdminDataProvider />}>
          <Route path="/" element={<AdminUsersPage />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );

  await user.click(await screen.findByRole("button", { name: copy.fr.addUser }));
  await user.type(screen.getByLabelText(copy.fr.username), "new.user");
  await user.type(screen.getByLabelText(copy.fr.fullName), "New User");
  await user.type(screen.getByLabelText(copy.fr.password), "password-test-123");
  await user.selectOptions(screen.getByRole("combobox", { name: copy.fr.role }), "3");
  await user.click(screen.getByRole("button", { name: copy.fr.createUser }));

  expect(api.admin.createUser).toHaveBeenCalledWith({
    username: "new.user",
    full_name: "New User",
    password: "password-test-123",
    role_id: 3,
  });
  expect(await screen.findByText("New User")).toBeTruthy();
  expect(screen.queryByText("password-test-123")).toBeNull();

  await user.selectOptions(screen.getByRole("combobox", { name: copy.fr.role }), "editeur");
  await waitFor(() => expect(api.admin.updateUserRole).toHaveBeenCalledWith("server-user-id", 2));
});

test("account approval accepts AccountRequestResponse and refreshes users", async () => {
  const createdUser = {
    user_id: "approved-server-user-id",
    username: "approved.user",
    full_name: "Approved User",
    role: "lecteur",
    is_active: true,
    created_at: "2026-11-24T10:00:00Z",
  };
  api.admin.users.mockResolvedValueOnce([]).mockResolvedValueOnce([createdUser]);
  api.admin.accountRequests.mockResolvedValue([{
    request_id: "request-1",
    username: createdUser.username,
    full_name: createdUser.full_name,
    status: "pending",
    created_at: "2026-11-11T09:32:00Z",
  }]);
  api.admin.decideAccountRequest.mockResolvedValue({
    request_id: "request-1",
    username: createdUser.username,
    full_name: createdUser.full_name,
    status: "approved",
    created_at: "2026-11-11T09:32:00Z",
    decided_by: "admin-id",
    decided_at: "2026-11-24T10:00:00Z",
  });
  api.admin.updateUserRole.mockResolvedValue({ ...createdUser, role: "editeur" });
  const user = userEvent.setup();

  render(
    <MemoryRouter initialEntries={["/requests"]}>
      <Routes>
        <Route element={<AdminDataProvider />}>
          <Route path="/requests" element={<><NavigateToUsers /><AdminRequestsPage /></>} />
          <Route path="/users" element={<AdminUsersPage />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );

  await user.selectOptions(await screen.findByRole("combobox", { name: copy.fr.chooseRole }), "lecteur");
  await user.click(screen.getByRole("button", { name: copy.fr.approve }));
  await user.click(screen.getByRole("button", { name: copy.fr.confirmApprove }));

  await waitFor(() => expect(api.admin.decideAccountRequest).toHaveBeenCalledWith("request-1", "approve", 3));
  await waitFor(() => expect(api.admin.users).toHaveBeenCalledTimes(2));
  await user.click(screen.getByRole("button", { name: "Aller aux utilisateurs" }));
  expect(await screen.findByText("Approved User")).toBeTruthy();

  await user.selectOptions(screen.getByRole("combobox", { name: copy.fr.role }), "editeur");
  await waitFor(() => expect(api.admin.updateUserRole).toHaveBeenCalledWith("approved-server-user-id", 2));
});

test("account requests include decided API rows but only pending rows can be acted on", async () => {
  api.admin.accountRequests.mockResolvedValue([
    {
      request_id: "request-approved",
      username: "approved.user",
      full_name: "Approved User",
      status: "approved",
      created_at: "2026-11-11T09:32:00Z",
      decided_by: "admin-id",
      decided_at: "2026-11-24T10:00:00Z",
    },
    {
      request_id: "request-pending",
      username: "pending.user",
      full_name: "Pending User",
      status: "pending",
      created_at: "2026-11-11T09:32:00Z",
      decided_by: null,
      decided_at: null,
    },
  ]);

  render(
    <MemoryRouter initialEntries={["/requests"]}>
      <Routes>
        <Route element={<AdminDataProvider />}>
          <Route path="/requests" element={<AdminRequestsPage />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );

  expect(await screen.findByText("Pending User")).toBeTruthy();
  expect(screen.queryByText("Approved User")).toBeNull();
  expect(screen.getByRole("button", { name: copy.fr.approve })).toBeTruthy();
});

test("account rejection accepts the AccountRequestResponse returned by the API", async () => {
  api.admin.accountRequests.mockResolvedValue([{
    request_id: "request-1",
    username: "pending.user",
    full_name: "Pending User",
    status: "pending",
    created_at: "2026-11-11T09:32:00Z",
  }]);
  api.admin.decideAccountRequest.mockResolvedValue({
    request_id: "request-1",
    username: "pending.user",
    full_name: "Pending User",
    status: "rejected",
    created_at: "2026-11-11T09:32:00Z",
    decided_by: "admin-id",
    decided_at: "2026-11-24T10:00:00Z",
  });
  const user = userEvent.setup();

  render(
    <MemoryRouter initialEntries={["/requests"]}>
      <Routes>
        <Route element={<AdminDataProvider />}>
          <Route path="/requests" element={<AdminRequestsPage />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );

  await user.click(await screen.findByRole("button", { name: copy.fr.reject }));
  await user.click(screen.getByRole("button", { name: copy.fr.confirmReject }));

  await waitFor(() => expect(api.admin.decideAccountRequest).toHaveBeenCalledWith("request-1", "reject"));
  await waitFor(() => expect(screen.queryByText("Pending User")).toBeNull());
  expect(setError).not.toHaveBeenCalled();
});

test("admin UI rejects a create response that does not match UserResponse", async () => {
  api.admin.createUser.mockResolvedValue({ status: "created" });
  const user = userEvent.setup();

  render(
    <MemoryRouter>
      <Routes>
        <Route element={<AdminDataProvider />}>
          <Route path="/" element={<AdminUsersPage />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );

  await user.click(await screen.findByRole("button", { name: copy.fr.addUser }));
  await user.type(screen.getByLabelText(copy.fr.username), "bad.response");
  await user.type(screen.getByLabelText(copy.fr.fullName), "Bad Response");
  await user.type(screen.getByLabelText(copy.fr.password), "password-test-123");
  await user.selectOptions(screen.getByRole("combobox", { name: copy.fr.role }), "3");
  await user.click(screen.getByRole("button", { name: copy.fr.createUser }));

  await waitFor(() => expect(setError).toHaveBeenCalledWith(
    copy.fr.invalidApiResponse.replace("{endpoint}", "POST /admin/users"),
  ));
  expect(screen.queryByText("Bad Response")).toBeNull();
});

test("admin web settings stay unchanged when the API response violates RoleResponse", async () => {
  api.admin.setRoleWeb.mockResolvedValue({ status: "updated" });
  const user = userEvent.setup();

  render(
    <MemoryRouter>
      <Routes>
        <Route element={<AdminDataProvider />}>
          <Route path="/" element={<AdminWebPage />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );

  const webSwitch = (await screen.findAllByRole("checkbox"))[0];
  await user.click(webSwitch);

  await waitFor(() => expect(setError).toHaveBeenCalledWith(
    copy.fr.invalidApiResponse.replace("{endpoint}", "PATCH /admin/roles/{role_id}/web"),
  ));
  expect(api.admin.setRoleWeb).toHaveBeenCalledWith(1, false);
  expect(webSwitch.checked).toBe(true);
});

test("audit log shows translated actions, named users, and readable detail fields", async () => {
  api.admin.users.mockResolvedValue([
    {
      user_id: "admin-id",
      username: "admin.user",
      full_name: "Admin User",
      role: "admin",
      is_active: true,
      created_at: "2026-11-24T10:00:00Z",
    },
    {
      user_id: "target-id",
      username: "target.user",
      full_name: "Target User",
      role: "lecteur",
      is_active: true,
      created_at: "2026-11-24T10:00:00Z",
    },
  ]);
  api.admin.audit.mockResolvedValue([{
    id: "audit-1",
    user_id: "admin-id",
    action: "update_role",
    details: { target_user_id: "target-id", new_role: "lecteur" },
    timestamp: "2026-11-27T10:00:00Z",
  }]);

  render(
    <MemoryRouter initialEntries={["/audit"]}>
      <Routes>
        <Route element={<AdminDataProvider />}>
          <Route path="/audit" element={<AdminAuditPage />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );

  expect(await screen.findByText("Modification du rôle d’un utilisateur")).toBeTruthy();
  expect(screen.getByText("Auteur: Admin User (@admin.user)")).toBeTruthy();
  expect(screen.getByText("Compte concerné")).toBeTruthy();
  expect(screen.getByText("Target User (@target.user)")).toBeTruthy();
  expect(screen.getByText("Lecteur")).toBeTruthy();
  expect(screen.queryByText("target-id")).toBeNull();
});
