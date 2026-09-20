import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useApp } from "../context/AppContext";
import MerchantPicker from "../components/MerchantPicker";

export default function Campaigns() {
  const { t, merchantId } = useApp();
  const [campaigns, setCampaigns] = useState([]);
  const [name, setName] = useState("");
  const [notice, setNotice] = useState("");
  const [type, setType] = useState("points_per_spend");
  const [points, setPoints] = useState(1);
  const [unit, setUnit] = useState(10);
  const [interactions, setInteractions] = useState(10);
  const [amount, setAmount] = useState(5);
  const [rounding, setRounding] = useState("floor");
  const [reward, setReward] = useState("");
  const [active, setActive] = useState(true);
  const [err, setErr] = useState("");
  const [deleting, setDeleting] = useState(null);
  const remove = async (id) => {
    if (!window.confirm(t("deleteCampaignConfirm"))) return;
    setDeleting(id); setErr("");
    try { const result = await api.deleteCampaign(merchantId, id); setCampaigns(items => items.filter(c => c.id !== id)); setNotice(t(result.pending_revocations ? "deletionPending" : "deletedSuccessfully")); }
    catch (e) { setErr(e.message); }
    finally { setDeleting(null); }
  };

  const load = () => {
    if (!merchantId) return;
    api.listCampaigns(merchantId).then(setCampaigns).catch((e) => setErr(String(e)));
  };
  useEffect(() => { setCampaigns([]); setErr(""); load(); }, [merchantId]);

  const buildConfig = () => {
    if (type === "points_per_spend") return { points: Number(points), amount_unit: Number(unit), rounding };
    if (type === "interaction") return { interactions_required: Number(interactions), reward_description: reward };
    return { amount: Number(amount), currency: "EUR" };
  };

  const create = async (e) => {
    e.preventDefault();
    setErr("");
    try {
      await api.createCampaign(merchantId, { name, type, config: buildConfig(), active });
      setName("");
      load();
    } catch (e) { setErr(String(e)); }
  };

  return (
    <>
      <h1>{t("campaigns")}</h1>
      <MerchantPicker />

      {!merchantId ? (
        <p className="note">{t("selectMerchantFirst")}</p>
      ) : (
        <>
          <div className="card">
            <h2>{t("campaigns")}</h2>
            <form onSubmit={create}>
              <label>{t("name")}<input required maxLength={200} value={name} onChange={e => setName(e.target.value)} /></label>
              <label>{t("type")}</label>
              <select aria-label={t("type")} value={type} onChange={(e) => setType(e.target.value)}>
                <option value="points_per_spend">{t("points_per_spend")}</option>
                <option value="interaction">{t("interaction")}</option>
                <option value="coupon">{t("coupon")}</option>
              </select>

              {type === "points_per_spend" && (
                <div className="row" style={{ marginTop: 8 }}>
                  <div><label>{t("points")}</label><input aria-label={t("points")} type="number" min="1" required value={points} onChange={(e) => setPoints(e.target.value)} /></div>
                  <div><label>{t("pointsPer")} (€)</label><input type="number" min="0.01" step="0.01" required value={unit} onChange={(e) => setUnit(e.target.value)} /></div>
                </div>
              )}
              {type === "interaction" && (
                <div className="row" style={{ marginTop: 8 }}>
                  <div><label>{t("interactionsRequired")}</label><input aria-label={t("interactionsRequired")} type="number" min="1" required value={interactions} onChange={(e) => setInteractions(e.target.value)} /></div>
                </div>
              )}
              {type === "coupon" && (
                <div className="row" style={{ marginTop: 8 }}>
                  <div><label>{t("couponAmount")}</label><input aria-label={t("couponAmount")} type="number" min="0.01" step="0.01" required value={amount} onChange={(e) => setAmount(e.target.value)} /></div>
                </div>
              )}

              {type === "points_per_spend" && <label>{t("rounding")}<select value={rounding} onChange={e => setRounding(e.target.value)}>{["floor", "ceil", "round"].map(r => <option key={r} value={r}>{t(r)}</option>)}</select></label>}
              {type === "interaction" && <label>{t("reward")}<input required value={reward} onChange={e => setReward(e.target.value)} /></label>}
              <label className="toggle"><input style={{width: "auto"}} type="checkbox" checked={active} onChange={e => setActive(e.target.checked)} />{t("active")}</label>
              <div className="btns">
                <button type="submit">{t("create")}</button>
                <button type="button" className="ghost" onClick={load}>{t("refresh")}</button>
              </div>
              {err && <p className="note" style={{ color: "#c81e1e" }}>{err}</p>}
            </form>
          </div>

          <div className="card">
            {notice && <p role="status">{notice}</p>}
            <table>
              <thead><tr><th>{t("name")}</th><th>{t("type")}</th><th>{t("config")}</th><th>{t("active")}</th><th>{t("actions")}</th></tr></thead>
              <tbody>
                {campaigns.length === 0 && <tr><td colSpan="5" className="note">{t("noData")}</td></tr>}
                {campaigns.map((c) => (
                  <tr key={c.id}>
                    <td>{c.name}</td>
                    <td>{t(c.type) !== c.type ? t(c.type) : c.type}</td>
                    <td className="note">{c.type === "points_per_spend" ? `${c.config.points} ${t("points")} / ${c.config.amount_unit} EUR (${t(c.config.rounding)})` : c.type === "interaction" ? `${c.config.interactions_required}: ${c.config.reward_description}` : `${c.config.amount} EUR`}</td>
                    <td><span className={"badge " + (c.active ? "active" : "inactive")}>{t(c.active ? "active" : "inactive")}</span></td>
                    <td><button className="small ghost" disabled={deleting !== null} onClick={() => remove(c.id)}>{t("delete")}</button></td>
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
