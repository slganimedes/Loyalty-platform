import { useEffect, useRef, useState } from "react";
import MerchantPicker from "../components/MerchantPicker";
import { useApp } from "../context/AppContext";
import { api } from "../api/client";

function PaymentForm({ merchantId }) {
  const { t } = useApp();
  const [customers, setCustomers] = useState([]);
  const [customerId, setCustomerId] = useState("");
  const [amount, setAmount] = useState("");
  const [source, setSource] = useState("other");
  const [loading, setLoading] = useState(true);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submitting = useRef(false);
  const pending = useRef(null);

  useEffect(() => {
    let active = true;
    api.listCustomers(merchantId)
      .then(data => { if (active) setCustomers(data); })
      .catch(e => { if (active) setErr(e.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [merchantId]);

  const submit = async e => {
    e.preventDefault();
    const customer = customers.find(c => c.id === customerId);
    if (submitting.current || !customer) return;
    submitting.current = true;
    setBusy(true); setErr(""); setResult(null);
    const payload = { merchant_id: merchantId, source, amount,
      identifiers: { customer_number: customer.customer_code } };
    const fingerprint = JSON.stringify(payload);
    // Retry a lost response with the same ID; start a new ID after success.
    if (pending.current?.fingerprint !== fingerprint) {
      pending.current = { fingerprint, id: `simulation-${crypto.randomUUID()}` };
    }
    try {
      setResult(await api.ingest({ ...payload, external_transaction_id: pending.current.id }));
      pending.current = null;
    } catch (e) { setErr(e.message); }
    finally { submitting.current = false; setBusy(false); }
  };

  return <form className="card" onSubmit={submit}>
    <div className="row">
      <div>
        <label htmlFor="tx-customer">{t("customer")}</label>
        <select id="tx-customer" required disabled={loading || busy} value={customerId} onChange={e => setCustomerId(e.target.value)}>
          <option value="">{t(loading ? "loading" : "selectCustomer")}</option>
          {customers.map(c => <option key={c.id} value={c.id}>{c.customer_code}{c.email ? ` \u00b7 ${c.email}` : ""}</option>)}
        </select>
      </div>
      <div>
        <label htmlFor="tx-amount">{t("amount")}</label>
        <input id="tx-amount" type="number" min="0" max="99999999.99" step="0.01" required disabled={busy} value={amount} onChange={e => setAmount(e.target.value)} />
      </div>
      <div>
        <label htmlFor="tx-source">{t("source")}</label>
        <select id="tx-source" disabled={busy} value={source} onChange={e => setSource(e.target.value)}>
          {["getnet", "ecommerce", "other"].map(s => <option key={s} value={s}>{t(s)}</option>)}
        </select>
      </div>
    </div>
    {!loading && !customers.length && !err && <p className="note">{t("noCustomersForPayment")}</p>}
    <div className="btns"><button disabled={busy || loading || !customerId}>{t("submitPayment")}</button></div>
    {err && <p role="alert" className="error">{err}</p>}
    {result && <p role="status">{t(result.status)} / {t("points")}: {result.points_delta}{result.new_balance !== null && ` / ${t("balance")}: ${result.new_balance}`}</p>}
  </form>;
}

export default function Transactions() {
  const { t, merchantId } = useApp();
  return <><h1>{t("transactions")}</h1><MerchantPicker />{merchantId && <PaymentForm key={merchantId} merchantId={merchantId} />}</>;
}
