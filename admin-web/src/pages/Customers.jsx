import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useApp } from "../context/AppContext";
import MerchantPicker from "../components/MerchantPicker";

export default function Customers() {
  const { t, merchantId, lang } = useApp();
  const [customers, setCustomers] = useState([]);
  const [form, setForm] = useState({ customer_code: "", email: "", dni: "", card_hash: "" });
  const [movements, setMovements] = useState(null);
  const [links, setLinks] = useState(null);
  const [err, setErr] = useState("");

  const load = () => {
    if (!merchantId) return;
    api.listCustomers(merchantId).then(setCustomers).catch((e) => setErr(String(e)));
  };
  useEffect(() => { setCustomers([]); setMovements(null); setLinks(null); setErr(""); load(); }, [merchantId]);

  const enroll = async (e) => {
    e.preventDefault();
    setErr("");
    try {
      await api.enrollCustomer(merchantId, {
        customer_code: form.customer_code,
        email: form.email || null,
        dni: form.dni || null,
        card_hash: form.card_hash || null,
      });
      setForm({ customer_code: "", email: "", dni: "", card_hash: "" });
      load();
    } catch (e) { setErr(String(e)); }
  };

  const showMovements = async (cid) => {
    try { const m = await api.getMovements(cid); setMovements({ cid, list: m }); } catch (e) { setErr(e.message); }
  };

  const showPasses = async (cid) => {
    try { const r = await api.refreshPasses(cid); setLinks(r.pass_links); load(); } catch (e) { setErr(e.message); }
  };
  return (
    <>
      <h1>{t("customers")}</h1>
      <MerchantPicker />

      {!merchantId ? (
        <p className="note">{t("selectMerchantFirst")}</p>
      ) : (
        <>
          <div className="card">
            <h2>{t("newCustomer")}</h2>
            <form onSubmit={enroll}>
              <div className="row">
                <div>
                  <label>{t("customerCode")}</label>
                  <input aria-label={t("customerCode")} value={form.customer_code} onChange={(e) => setForm({ ...form, customer_code: e.target.value })} required />
                </div>
                <div>
                  <label>{t("email")}</label>
                  <input aria-label={t("email")} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
                </div>
                <div>
                  <label>{t("dni")}</label>
                  <input aria-label={t("dni")} value={form.dni} onChange={(e) => setForm({ ...form, dni: e.target.value })} />
                </div>
                <div>
                  <label>{t("cardHash")}</label>
                  <input aria-label={t("cardHash")} value={form.card_hash} onChange={(e) => setForm({ ...form, card_hash: e.target.value })} pattern="[0-9a-f]{64}" placeholder="HMAC-SHA256" autoComplete="off" />
                </div>
              </div>
              <div className="btns">
                <button type="submit">{t("enroll")}</button>
                <button type="button" className="ghost" onClick={load}>{t("refresh")}</button>
              </div>
              {err && <p className="note" style={{ color: "#c81e1e" }}>{err}</p>}
            </form>
          </div>

          <div className="card">
            <h2>{t("customers")}</h2>
            <table>
              <thead>
                <tr><th>{t("customerCode")}</th><th>{t("email")}</th><th>{t("balance")}</th><th>{t("actions")}</th></tr>
              </thead>
              <tbody>
                {customers.length === 0 && <tr><td colSpan="4" className="note">{t("noData")}</td></tr>}
                {customers.map((c) => (
                  <tr key={c.id}>
                    <td>{c.customer_code}</td>
                    <td className="note">{c.email || "—"}</td>
                    <td><strong>{c.points_balance}</strong> {t("points")}</td>
                    <td><button className="small ghost" onClick={() => showMovements(c.id)}>{t("movements")}</button>{" "}<button className="small ghost" onClick={() => showPasses(c.id)}>{t("passes")}</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {links && <div className="card"><h2>{t("passes")}</h2>{Object.keys(links).length === 0 ? <p>{t("noPasses")}</p> : Object.entries(links).map(([provider, url]) => <p key={provider}><a href={url} target="_blank" rel="noreferrer">{t(provider)}</a></p>)}</div>}
          {movements && (
            <div className="card">
              <h2>{t("movements")} · {movements.cid.slice(0, 8)}…</h2>
              <table>
                <thead><tr><th>{t("type")}</th><th>Δ {t("points")}</th><th>{t("date")}</th></tr></thead>
                <tbody>
                  {movements.list.length === 0 && <tr><td colSpan="3" className="note">{t("noData")}</td></tr>}
                  {movements.list.map((m) => (
                    <tr key={m.id}>
                      <td>{t(m.type)}{m.description && <p className="note">{m.description}</p>}</td>
                      <td>{m.points_delta > 0 ? "+" : ""}{m.points_delta}</td>
                      <td className="note">{new Date(m.created_at).toLocaleString(lang)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  );
}
