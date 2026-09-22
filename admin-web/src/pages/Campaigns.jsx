import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useApp } from "../context/AppContext";
import MerchantPicker from "../components/MerchantPicker";
import CampaignEditor from "../components/CampaignEditor";

export default function Campaigns() {
  const { t, merchantId } = useApp();
  const [campaigns, setCampaigns] = useState([]);
  const [editing, setEditing] = useState(null);
  const [notice, setNotice] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => merchantId && api.listCampaigns(merchantId).then(setCampaigns).catch(e => setErr(e.message));
  useEffect(() => {
    let alive = true;
    setCampaigns([]); setEditing(null); setErr(""); setNotice("");
    if (merchantId) api.listCampaigns(merchantId).then(rows => { if (alive) setCampaigns(rows); }).catch(e => { if (alive) setErr(e.message); });
    return () => { alive = false; };
  }, [merchantId]);
  const change = async (id, archive) => {
    if (!window.confirm(t(archive ? "archiveCampaignConfirm" : "deleteCampaignConfirm"))) return;
    setBusy(true); setErr("");
    try {
      const result = archive ? await api.archiveCampaign(id) : await api.deleteCampaign(merchantId, id);
      setNotice(t(result.pending_revocations ? "deletionPending" : archive ? "campaignArchived" : "deletedSuccessfully"));
      await load();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  return <>
    <h1>{t("campaigns")}</h1><MerchantPicker />
    {err && <p role="alert" className="error">{err}</p>}{notice && <p role="status">{notice}</p>}
    {!merchantId ? <p className="note">{t("selectMerchantFirst")}</p> : editing !== null ?
      <CampaignEditor key={`${merchantId}-${editing.id || "new"}`} merchantId={merchantId} campaign={editing.id ? editing : null} onCancel={() => setEditing(null)} onSaved={() => {setEditing(null); setNotice(t("saved")); load();}} /> :
      <div className="card">
        <div className="btns"><button onClick={() => setEditing({})}>{t("newCampaign")}</button><button className="ghost" onClick={load}>{t("refresh")}</button></div>
        <table><thead><tr><th>{t("name")}</th><th>{t("type")}</th><th>{t("status")}</th><th>{t("actions")}</th></tr></thead>
          <tbody>{!campaigns.length && <tr><td colSpan={4}>{t("noData")}</td></tr>}{campaigns.map(c => <tr key={c.id}>
            <td>{c.name}</td><td>{t(c.type)}</td><td><span className={`badge ${c.active ? "active" : "inactive"}`}>{t(c.lifecycle === "draft" ? "draft" : c.active ? "active" : "inactive")}</span></td>
            <td><button className="small ghost" disabled={busy} onClick={() => setEditing(c)}>{t("edit")}</button>{" "}{c.active && <button className="small ghost" disabled={busy} onClick={() => change(c.id, true)}>{t("archive")}</button>}{" "}<button className="small ghost" disabled={busy} onClick={() => change(c.id, false)}>{t("delete")}</button></td>
          </tr>)}</tbody>
        </table>
      </div>}
  </>;
}
