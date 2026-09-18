import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useApp } from "../context/AppContext";
import MerchantPicker from "../components/MerchantPicker";

export default function Coupons() {
  const { t, merchantId } = useApp();
  const [coupons, setCoupons] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [customerId, setCustomerId] = useState("");
  const [amount, setAmount] = useState(5);
  const [err, setErr] = useState("");

  const load = () => {
    if (!merchantId) return;
    api.listCoupons(merchantId).then(setCoupons).catch((e) => setErr(String(e)));
    api.listCustomers(merchantId).then(setCustomers).catch((e) => setErr(e.message));
  };
  useEffect(() => { setCoupons([]); setCustomers([]); setCustomerId(""); setErr(""); load(); }, [merchantId]);

  const issue = async (e) => {
    e.preventDefault();
    setErr("");
    try {
      await api.issueCoupon(merchantId, { customer_id: customerId, amount: Number(amount) });
      load();
    } catch (e) { setErr(String(e)); }
  };

  return (
    <>
      <h1>{t("coupons")}</h1>
      <MerchantPicker />

      {!merchantId ? (
        <p className="note">{t("selectMerchantFirst")}</p>
      ) : (
        <>
          <div className="card">
            <h2>{t("issueCoupon")}</h2>
            <form onSubmit={issue}>
              <div className="row">
                <div>
                  <label>{t("customers")}</label>
                  <select aria-label={t("customers")} value={customerId} onChange={(e) => setCustomerId(e.target.value)} required>
                    <option value="">—</option>
                    {customers.map((c) => (
                      <option key={c.id} value={c.id}>{c.customer_code} · {c.email || ""}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label>{t("amount")}</label>
                  <input aria-label={t("amount")} type="number" min="0.01" step="0.01" required value={amount} onChange={(e) => setAmount(e.target.value)} />
                </div>
              </div>
              <div className="btns">
                <button type="submit">{t("issueCoupon")}</button>
                <button type="button" className="ghost" onClick={load}>{t("refresh")}</button>
              </div>
              {err && <p className="note" style={{ color: "#c81e1e" }}>{err}</p>}
            </form>
          </div>

          <div className="card">
            <table>
              <thead><tr><th>{t("amount")}</th><th>{t("status")}</th><th>{t("id")}</th></tr></thead>
              <tbody>
                {coupons.length === 0 && <tr><td colSpan="3" className="note">{t("noData")}</td></tr>}
                {coupons.map((c) => (
                  <tr key={c.id}>
                    <td>€{Number(c.amount).toFixed(2)}</td>
                    <td><span className={"badge " + c.status}>{t(c.status) !== c.status ? t(c.status) : c.status}</span></td>
                    <td className="note">{c.id.slice(0, 8)}…</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}
