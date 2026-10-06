import { NavLink, Outlet } from "react-router-dom";
import { useAuth, useIdleLogout } from "../auth/AuthContext";
import { he } from "../i18n/he";
import { navFor } from "../lib/roles";

export const IDLE_MINUTES = 15;

export function Layout() {
  const { user, logout } = useAuth();
  useIdleLogout(IDLE_MINUTES, () => void logout(true));
  const links = navFor(user!.role);
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">⛨</span>
          <span>{he.app.name}<small>{he.app.tagline}</small></span>
        </div>
        <nav className="nav" aria-label={he.nav.main}>
          {links.map((l) => (
            <NavLink key={l.to} to={l.to} end={l.end}>
              <span aria-hidden="true">{l.icon}</span>{he.nav[l.label]}
            </NavLink>
          ))}
          <button className="grow" onClick={() => void logout()}><span aria-hidden="true">⎋</span>{he.nav.logout}</button>
        </nav>
      </aside>
      <main className="main" id="main">
        <Outlet />
      </main>
      <nav className="bottom-nav" aria-label={he.nav.main} style={{ gridTemplateColumns: `repeat(${links.length}, 1fr)` }}>
        {links.map((l) => (
          <NavLink key={l.to} to={l.to} end={l.end}>
            <span aria-hidden="true">{l.icon}</span>{he.nav[l.label]}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
