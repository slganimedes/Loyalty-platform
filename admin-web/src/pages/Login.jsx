import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useApp } from "../context/AppContext";

export default function Login() {
  const { t, lang, changeLang, login, user } = useApp();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr("");
    try { await login(username, password); navigate("/merchants"); }
    catch (e) { setErr(t("loginFailed")); }
    finally { setBusy(false); }
  };

  if (user?.public_access) return <Navigate to="/merchants" replace />;
  return (
    <div className="login-wrap">
      <form className="login-box" onSubmit={submit}>
        <h1>🎟️ {t("appTitle")}</h1>
        <p className="note">{t("login")}</p>
        <label>{t("username")}</label>
        <input aria-label={t("username")} autoComplete="username" required value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
        <label>{t("password")}</label>
        <input aria-label={t("password")} autoComplete="current-password" required type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        <div className="btns">
          <button type="submit" disabled={busy}>{t("signIn")}</button>
          <select value={lang} onChange={(e) => changeLang(e.target.value)} style={{ width: 90 }}>
            <option value="es">ES</option>
            <option value="en">EN</option>
          </select>
        </div>
        {err && <p role="alert" className="error">{err}</p>}
      </form>
    </div>
  );
}
