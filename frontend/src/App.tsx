import { useEffect, useState } from "react";
import { api } from "./api";
import { Login } from "./pages/Login";
import { Home } from "./pages/Home";
import { Settings } from "./pages/Settings";
import { ComingSoon } from "./pages/ComingSoon";

function useHashRoute(): string {
  const [route, setRoute] = useState(() => window.location.hash.replace(/^#/, "") || "/");
  useEffect(() => {
    const on = () => setRoute(window.location.hash.replace(/^#/, "") || "/");
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export function App() {
  const route = useHashRoute();
  const [authed, setAuthed] = useState<boolean | null>(null);

  useEffect(() => {
    api<{ authenticated: boolean }>("/api/auth/me")
      .then((r) => setAuthed(r.authenticated))
      .catch(() => setAuthed(false));
  }, []);

  if (authed === null) return <div className="center muted">लोड हो रहा है…</div>;
  if (!authed) return <Login onDone={() => setAuthed(true)} />;

  const logout = async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => {});
    setAuthed(false);
  };

  let page;
  if (route.startsWith("/settings")) page = <Settings />;
  else if (route.startsWith("/edit")) page = <ComingSoon title="वीडियो एडिट करो" phase="Phase 2" />;
  else if (route.startsWith("/create")) page = <ComingSoon title="टॉपिक से वीडियो बनाओ" phase="Phase 3" />;
  else page = <Home />;

  return (
    <div className="app">
      <header className="topbar">
        <a className="brand" href="#/">AI YT Studio</a>
        <nav>
          <a href="#/settings" className={route.startsWith("/settings") ? "active" : ""}>सेटिंग्स</a>
          <button className="link" onClick={logout}>लॉग-आउट</button>
        </nav>
      </header>
      <main className="page">{page}</main>
    </div>
  );
}
