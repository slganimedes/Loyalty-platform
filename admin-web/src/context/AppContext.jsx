import { createContext, useContext, useEffect, useState } from "react";
import { translations } from "../i18n";
import { api } from "../api/client";

const AppContext = createContext(null);
export function AppProvider({ children }) {
  const [lang, setLang] = useState(localStorage.getItem("lang") === "en" ? "en" : "es");
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);
  const [merchantId, setMerchantId] = useState("");
  const [error, setError] = useState("");
  const t = (key) => translations[lang][key] ?? key;
  function applyUser(u) {
    setUser(u); setLang(u.language); localStorage.setItem("lang", u.language);
    setMerchantId(u.merchant_id || "");
  }
  useEffect(() => {
    const expired = () => { setUser(null); setMerchantId(""); sessionStorage.removeItem("token"); };
    window.addEventListener("session-expired", expired);
    if (sessionStorage.getItem("token")) api.me().then(applyUser).catch(expired).finally(() => setReady(true));
    else setReady(true);
    return () => window.removeEventListener("session-expired", expired);
  }, []);
  useEffect(() => { document.documentElement.lang = lang; }, [lang]);
  const changeLang = async (language) => {
    setError("");
    try {
      if (user) { const u = await api.language(language); setUser(u); }
      setLang(language); localStorage.setItem("lang", language);
    } catch (e) { setError(e.message); }
  };
  const login = async (username, password) => {
    const response = await api.login({ username, password });
    sessionStorage.setItem("token", response.access_token); applyUser(response.user);
  };
  const logout = async () => {
    try { await api.logout(); } catch (e) { setError(e.message); }
    sessionStorage.removeItem("token"); setUser(null); setMerchantId("");
  };
  return <AppContext.Provider value={{lang, changeLang, t, user, ready, login, logout, merchantId, selectMerchant: setMerchantId, error}}>{children}</AppContext.Provider>;
}
export const useApp = () => useContext(AppContext);
