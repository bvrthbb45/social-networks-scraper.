import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { Spinner } from "./components/ui";
import { homeFor, navFor } from "./lib/roles";
import { Account } from "./pages/Account";
import { Audit } from "./pages/Audit";
import { Dashboard } from "./pages/Dashboard";
import { FindingDetailPage } from "./pages/FindingDetail";
import { Findings } from "./pages/Findings";
import { Imports } from "./pages/Imports";
import { Login } from "./pages/login";
import { People } from "./pages/People";
import { Users } from "./pages/Users";
import { Watchlist } from "./pages/Watchlist";
import type { ReactNode } from "react";
import type { Role } from "./api/types";

function Guard({ path, role, children }: { path: string; role: Role; children: ReactNode }) {
  return navFor(role).some((n) => n.to === path) ? <>{children}</> : <Navigate to={homeFor(role)} replace />;
}

export function Gate() {
  const { user, loading } = useAuth();
  if (loading) return <Spinner />;
  if (!user) return <Login />;
  const g = (path: string, el: ReactNode) => <Guard path={path} role={user.role}>{el}</Guard>;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={g("/", <Dashboard />)} />
        <Route path="findings" element={g("/findings", <Findings />)} />
        <Route path="findings/:id" element={g("/findings", <FindingDetailPage />)} />
        <Route path="people" element={g("/people", <People />)} />
        <Route path="imports" element={g("/imports", <Imports />)} />
        <Route path="watchlist" element={g("/watchlist", <Watchlist />)} />
        <Route path="users" element={g("/users", <Users />)} />
        <Route path="audit" element={g("/audit", <Audit />)} />
        <Route path="account" element={g("/account", <Account />)} />
        <Route path="*" element={<Navigate to={homeFor(user.role)} replace />} />
      </Route>
    </Routes>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Gate />
      </AuthProvider>
    </BrowserRouter>
  );
}
