import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useApp } from "../context/AppContext";

export default function Layout() {
  const { t, lang, changeLang, user, logout, error } = useApp();
  const navigate = useNavigate();
  const [apiOk, setApiOk] = useState(null);

  useEffect(() => {
    api.health().then(() => setApiOk(true)).catch(() => setApiOk(false));
  }, []);

  const doLogout = async () => {
    await logout();
    navigate("/login");
  };

  const links = [
    ["/merchants", "nav_merchants"],
    ["/customers", "nav_customers"],
    ["/campaigns", "nav_campaigns"],
    ["/passes", "passes"],
    ["/coupons", "nav_coupons"],
    ["/transactions", "transactions"],
    ...(user?.role === "super_admin" ? [["/wallet", "nav_wallet"]] : []),
  ];

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand"><span className="brand-name">getnet<span>.</span></span><span className="brand-subtitle">{t("appTitle")}</span></div>
        <nav className="nav">
          {links.map(([to, key]) => (
            <NavLink key={to} to={to} className={({ isActive }) => (isActive ? "active" : "")}>
              {t(key)}
            </NavLink>
          ))}
          <a href="/docs" target="_blank" rel="noreferrer">{t("apiDocs")} &#8599;</a>
        </nav>
        <div className="foot">
          <span className={"dot " + (apiOk ? "ok" : "bad")} />{" "}
          {apiOk ? t("apiConnected") : t("apiError")}
        </div>
      </aside>

      <div className="main">
        <div className="topbar">
          <div className="note">{user?.role === "super_admin" ? "Super Admin" : "SME Admin"} · {user?.username}</div>
          <div className="right">
            <select aria-label={t("language")} value={lang} onChange={(e) => changeLang(e.target.value)} style={{ width: 90 }}>
              <option value="es">ES</option>
              <option value="en">EN</option>
            </select>
            <button className="ghost small" onClick={doLogout}>{t("logout")}</button>
          </div>
        </div>
        <div className="content">
          {error && <p role="alert" className="error">{error}</p>}
          <Outlet />
        </div>
      </div>
    </div>
  );
}
