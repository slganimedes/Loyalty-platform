import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api } from "../api/client";
import { useApp } from "../context/AppContext";

const fields = {
  apple: [["pass_type_id", "passTypeId"], ["team_id", "teamId"], ["cert_path", "certPath"], ["cert_password", "certPassword"], ["wwdr_cert_path", "wwdrPath"], ["webservice_url", "webserviceUrl"]],
  google: [["issuer_id", "issuerId"], ["sa_json", "saJson"]],
};
export default function WalletConfig() {
  const { t, user } = useApp();
  const [cfg, setCfg] = useState(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const load = async () => {
    try { setCfg(await api.getWallet()); } catch (e) { setErr(e.message); }
  };
  useEffect(() => { if (user.role === "super_admin") load(); }, [user.role]);
  if (user.role !== "super_admin") return <Navigate to="/merchants" replace />;
  const save = async (provider) => {
    setBusy(true); setErr(""); setMsg("");
    try {
      const config = Object.fromEntries(Object.entries(cfg[`${provider}_config`]).filter(([, value]) => value && value !== "********"));
      await (provider === "apple" ? api.setApple : api.setGoogle)({enabled: cfg[`${provider}_enabled`], config});
      await load(); setMsg(t("saved"));
    } catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  };
  return <><h1>{t("walletConfig")}</h1><p className="note">{t("walletHint")}</p>
    {err && <p role="alert" className="error">{err}</p>}{msg && <p role="status">{msg}</p>}
    {!cfg ? <p>{t("loading")}</p> : ["apple", "google"].map(provider => <section className="card" key={provider}>
      <h2>{t(provider)}</h2>
      <label className="toggle"><input type="checkbox" style={{width: "auto"}} checked={cfg[`${provider}_enabled`]} onChange={e => setCfg({...cfg, [`${provider}_enabled`]: e.target.checked})} />{t("enabled")} {t(provider)}</label>
      <div className="row">{fields[provider].map(([key, label]) => {
        const value = cfg[`${provider}_config`]?.[key] || "";
        return <div key={key}><label htmlFor={`${provider}-${key}`}>{t(label)}</label><input id={`${provider}-${key}`} type={key === "cert_password" ? "password" : "text"} autoComplete="off" value={value === "********" ? "" : value} placeholder={value === "********" ? t("storedSecret") : ""} onChange={e => setCfg({...cfg, [`${provider}_config`]: {...cfg[`${provider}_config`], [key]: e.target.value}})} /></div>;
      })}</div>
      <div className="btns"><button disabled={busy} onClick={() => save(provider)}>{t("save")} {t(provider)}</button></div>
    </section>)}
  </>;
}
