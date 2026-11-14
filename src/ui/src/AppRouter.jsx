import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router-dom";
import { useApp, AppProvider } from "./app/AppContext.jsx";
import { AccountRequestPage, LoginPage } from "./pages/auth/AuthPages.jsx";
import ChatPage from "./pages/chat/ChatPage.jsx";
import DocumentsPage from "./pages/documents/DocumentsPage.jsx";
import {
  AdminAuditPage, AdminDataProvider, AdminOverviewPage, AdminRequestsPage,
  AdminUsersPage, AdminWebPage,
} from "./pages/admin/AdminRoutes.jsx";
import WorkspaceLayout from "./components/WorkspaceLayout.jsx";

function RequireAuth() {
  const { user } = useApp();
  return user ? <Outlet /> : <Navigate to="/login" replace />;
}

function RequireRole({ roles }) {
  const { user } = useApp();
  if (!roles.includes(user.role)) {
    return <Navigate to={user.role === "admin" ? "/admin" : `/${user.role}/chat`} replace />;
  }
  return <Outlet />;
}

function HomeRedirect() {
  const { user } = useApp();
  return <Navigate to={user ? (user.role === "admin" ? "/admin" : `/${user.role}/chat`) : "/login"} replace />;
}

function RouteTable() {
  return <Routes>
    <Route path="/" element={<HomeRedirect />} />
    <Route path="/login" element={<LoginPage />} />
    <Route path="/demande-compte" element={<AccountRequestPage />} />
    <Route element={<RequireAuth />}>
      <Route element={<WorkspaceLayout />}>
        <Route element={<RequireRole roles={["lecteur"]} />}>
          <Route path="/lecteur" element={<Navigate to="/lecteur/chat" replace />} />
          <Route path="/lecteur/chat" element={<ChatPage />} />
          <Route path="/lecteur/documents" element={<DocumentsPage role="lecteur" />} />
        </Route>
        <Route element={<RequireRole roles={["editeur"]} />}>
          <Route path="/editeur" element={<Navigate to="/editeur/chat" replace />} />
          <Route path="/editeur/chat" element={<ChatPage />} />
          <Route path="/editeur/documents" element={<DocumentsPage role="editeur" />} />
        </Route>
        <Route element={<RequireRole roles={["admin"]} />}>
          <Route path="/admin" element={<AdminDataProvider />}>
            <Route index element={<AdminOverviewPage />} />
            <Route path="users" element={<AdminUsersPage />} />
            <Route path="requests" element={<AdminRequestsPage />} />
            <Route path="documents" element={<DocumentsPage role="admin" />} />
            <Route path="web" element={<AdminWebPage />} />
            <Route path="audit" element={<AdminAuditPage />} />
          </Route>
        </Route>
      </Route>
    </Route>
    <Route path="*" element={<HomeRedirect />} />
  </Routes>;
}

export default function AppRouter() {
  return <BrowserRouter><AppProvider><RouteTable /></AppProvider></BrowserRouter>;
}