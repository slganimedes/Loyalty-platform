import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import QRCode from "qrcode";
import MerchantPicker from "../components/MerchantPicker";
import { api } from "../api/client";
import { useApp } from "../context/AppContext";

function PassManager({ merchantId, initialCustomer }) {
  const { t } = useApp();
  const [rows, setRows] = useState([]);
  const [campaigns, setCampaigns] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [campaignId, setCampaignId] = useState("");
  const [customerId, setCustomerId] = useState(initialCustomer || "");
  const [platform, setPlatform] = useState("google");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [notice, setNotice] = useState("");
  const [installation, setInstallation] = useState(null);
  const [showDeleted, setShowDeleted] = useState(false);
  const load = async () => setRows(await api.listPasses(merchantId));
  useEffect(() => {
    let alive = true;
    Promise.all([api.listPasses(merchantId), api.listCampaigns(merchantId), api.listCustomers(merchantId)])
      .then(([passes, campaigns, customers]) => {
        if (!alive) return;
        setRows(passes); setCampaigns(campaigns); setCustomers(customers);
        if (!customers.some(c => c.id === initialCustomer)) setCustomerId("");
      }).catch(e => { if (alive) setErr(e.message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [merchantId, initialCustomer]);
  const display = async (result) => {
    if (!result.url) { setErr(t("passIssueFailed")); return; }
    const qr = await QRCode.toDataURL(result.url, { width: 440, margin: 4, errorCorrectionLevel: "M" });
    setInstallation({ ...result, qr });
  };
  const assign = async e => {
    e.preventDefault(); setBusy(true); setErr(""); setNotice(""); setInstallation(null);
    try { await display(await api.assignPass(customerId, {campaign_id: campaignId, platform})); await load(); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const open = async row => {
    setBusy(true); setErr(""); setInstallation(null);
    try { await display(await api.passLink(row.customer_id, row.id)); await load(); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const remove = async row => {
    if (row.status !== "revoked" && !window.confirm(t("deletePassConfirm"))) return;
    setBusy(true); setErr(""); setInstallation(null);
    try {
      const result = await api.deletePass(row.customer_id, row.id);
      setNotice(t(result.provider_synced ? "passDeleted" : "passDeletePending"));
      await load();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  return <>
    <form className="card" onSubmit={assign}>
      <h2>{t("assignPass")}</h2>
      <p className="note">{t("campaignPassHint")}</p>
      <div className="row">
        <label>{t("campaign")}<select aria-label={t("campaign")} required disabled={busy || loading} value={campaignId} onChange={e => setCampaignId(e.target.value)}>
          <option value="">{t("selectCampaign")}</option>
          {campaigns.filter(c => c.active).map(c => <option key={c.id} value={c.id}>{c.name} · {t(c.type)}</option>)}
        </select></label>
        <label>{t("customer")}<select aria-label={t("customer")} required disabled={busy || loading} value={customerId} onChange={e => setCustomerId(e.target.value)}>
          <option value="">{t("selectCustomer")}</option>
          {customers.map(c => <option key={c.id} value={c.id}>{c.customer_code}{c.email ? ` · ${c.email}` : ""}</option>)}
        </select></label>
        <label>{t("provider")}<select aria-label={t("provider")} disabled={busy} value={platform} onChange={e => setPlatform(e.target.value)}><option value="google">Google Wallet</option><option value="apple">Apple Wallet</option></select></label>
      </div>
      <div className="btns"><button disabled={busy || loading || !campaignId || !customerId}>{t("assignPass")}</button></div>
    </form>
    {err && <p role="alert" className="error">{err}</p>}
    {notice && <p role="status">{notice}</p>}
    {installation && <div className="card">
      <h2>{t("walletEnrollment")}</h2>
      <p>{installation.pass.campaign_name || t("legacyPass")} · {installation.pass.customer_code} · {t(installation.pass.platform)}</p>
      <label>{t("passUrl")}<textarea readOnly value={installation.url} rows={4} /></label>
      <p><a href={installation.url} target="_blank" rel="noreferrer">{t("openPass")}</a></p>
      <img className="enrollment-qr" src={installation.qr} alt={t("enrollmentQr")} />
      <p className="note">{t("enrollmentHint")}</p>
    </div>}
    <div className="card">
      <label className="toggle"><input type="checkbox" checked={showDeleted} onChange={e => setShowDeleted(e.target.checked)} />{t("showDeletedPasses")}</label>
      <button className="small ghost" disabled={busy} onClick={() => load().catch(e => setErr(e.message))}>{t("refresh")}</button>
      <table><thead><tr><th>{t("campaign")}</th><th>{t("customer")}</th><th>{t("provider")}</th><th>{t("status")}</th><th>{t("actions")}</th></tr></thead>
        <tbody>{rows.filter(row => showDeleted || row.status === "active" || row.sync_pending).map(row => <tr key={row.id}>
          <td>{row.campaign_name || t("legacyPass")}</td><td>{row.customer_code}</td><td>{t(row.platform)}</td>
          <td>{t(row.status === "revoked" ? "revoked" : "active")}{row.sync_pending && <p className="note">{t("syncPending")}</p>}</td>
          <td>{row.status === "active" ? <><button className="small ghost" disabled={busy} onClick={() => open(row)}>{t("showUrlQr")}</button>{" "}<button className="small ghost" disabled={busy} onClick={() => remove(row)}>{t("delete")}</button></> : row.sync_pending && <button className="small ghost" disabled={busy} onClick={() => remove(row)}>{t("retryDelete")}</button>}</td>
        </tr>)}</tbody>
      </table>
      {!rows.length && <p>{t("noAssignedPasses")}</p>}
    </div>
  </>;
}

export default function Passes() {
  const {t, merchantId} = useApp();
  const [params] = useSearchParams();
  return <><h1>{t("passes")}</h1><MerchantPicker />{merchantId ? <PassManager key={merchantId} merchantId={merchantId} initialCustomer={params.get("customer")} /> : <p>{t("selectMerchantFirst")}</p>}</>;
}
