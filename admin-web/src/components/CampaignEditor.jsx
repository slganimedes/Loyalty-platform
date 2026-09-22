import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { useApp } from "../context/AppContext";
import PassPreview from "./PassPreview";

export default function CampaignEditor({ merchantId, campaign, onSaved, onCancel }) {
  const { t, lang } = useApp();
  const [name, setName] = useState(campaign?.name || "");
  const [description, setDescription] = useState(campaign?.description || "");
  const [type, setType] = useState(campaign?.type || "points_per_spend");
  const [config, setConfig] = useState(campaign?.config || {points: 1, amount_unit: 10, rounding: "floor"});
  const [active, setActive] = useState(campaign?.active ?? true);
  const [design, setDesign] = useState(() => ({logo_asset_id: null, hero_asset_id: null, background_color: "#373839", logo_description: "", hero_description: "", subheader: lang === "es" ? "Cliente" : "Customer", locale: lang === "es" ? "es-ES" : "en-US", ...campaign?.design, points_label: campaign?.design?.points_label || t("points"), member_since_label: campaign?.design?.member_since_label || t("memberSince"), barcode_alternate_text: campaign?.design?.barcode_alternate_text || t("barcodeDefault")}));
  const [images, setImages] = useState({logo: "", hero: ""});
  const [customers, setCustomers] = useState([]);
  const [members, setMembers] = useState([]);
  const [selected, setSelected] = useState([]);
  const [search, setSearch] = useState("");
  const [merchantName, setMerchantName] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const uploaded = useRef(new Set());
  const urls = useRef([]);
  const alive = useRef(true);
  const field = (key, value) => { setDesign(d => ({...d, [key]: value})); setReviewed(false); };
  useEffect(() => {
    alive.current = true;
    Promise.all([api.listCustomers(merchantId), api.listMerchants(), campaign ? api.campaignCustomers(campaign.id) : []]).then(async ([people, merchants, enrollments]) => {
      if (!alive.current) return;
      setCustomers(people); setMembers(enrollments); setMerchantName(merchants.find(m => m.id === merchantId)?.name || "");
      for (const kind of ["logo", "hero"]) {
        const id = campaign?.design?.[`${kind}_asset_id`];
        if (id) {
          const blob = await api.assetContent(merchantId, id);
          if (!alive.current) return;
          const url = URL.createObjectURL(blob); urls.current.push(url); setImages(prev => ({...prev, [kind]: url}));
        }
      }
    }).catch(e => { if (alive.current) setErr(e.message); }).finally(() => {if (alive.current) setLoading(false);});
    return () => {
      alive.current = false;
      urls.current.forEach(URL.revokeObjectURL);
      // Unattached uploads are also collected by the server after 24 hours.
      uploaded.current.forEach(id => api.deletePassAsset(merchantId, id).catch(() => {}));
    };
  }, [merchantId, campaign?.id]);
  const upload = async (kind, file) => {
    if (!file) return;
    setBusy(true); setErr(""); setReviewed(false);
    try {
      const asset = await api.uploadPassAsset(merchantId, file);
      if (!alive.current) { await api.deletePassAsset(merchantId, asset.id); return; }
      const previous = design[`${kind}_asset_id`];
      uploaded.current.add(asset.id);
      if (uploaded.current.has(previous)) { await api.deletePassAsset(merchantId, previous); uploaded.current.delete(previous); }
      const url = URL.createObjectURL(file); urls.current.push(url);
      field(`${kind}_asset_id`, asset.id); setImages(prev => ({...prev, [kind]: url}));
    } catch (e) { if (alive.current) setErr(e.message); }
    finally { if (alive.current) setBusy(false); }
  };
  const save = async e => {
    e.preventDefault(); setErr("");
    if (!design.logo_asset_id || !design.hero_asset_id) { setErr(t("bothImagesRequired")); return; }
    setBusy(true);
    try {
      const body = {name, description, type, config, active, lifecycle: "ready", design, customer_ids: selected};
      if (campaign) await api.updateCampaign(campaign.id, body); else await api.createCampaign(merchantId, body);
      uploaded.current.clear(); onSaved();
    } catch (e) { setErr(e.message); }
    finally { if (alive.current) setBusy(false); }
  };
  const changeMembership = async (row, status) => {
    if (status !== "active" && !window.confirm(t("cancelMembershipConfirm"))) return;
    setBusy(true); setErr("");
    try { await api.membership(campaign.id, row.customer_id, status); setMembers(await api.campaignCustomers(campaign.id)); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  return <form className="campaign-editor" onSubmit={save} aria-busy={busy || loading} onChange={() => setReviewed(false)}>
    {err && <p role="alert" id="campaign-error" className="error">{err}</p>}
    {campaign?.design?.legacy_review_required && <p role="status">{t("legacyDesignReview")}</p>}
    {loading && <p role="status">{t("loading")}</p>}
    {busy && <p role="status">{t("uploading")}</p>}
    <fieldset disabled={busy || loading} aria-describedby={err ? "campaign-error" : undefined}>
      <section className="card"><h2>1. {t("campaignDetails")}</h2>
        <label>{t("name")}<input required maxLength={200} value={name} onChange={e => setName(e.target.value)} /></label>
        <label>{t("description")}<textarea maxLength={2000} value={description} onChange={e => setDescription(e.target.value)} /></label>
        <label>{t("type")}<select aria-label={t("type")} value={type} disabled={!!campaign} onChange={e => {setType(e.target.value); setConfig(e.target.value === "points_per_spend" ? {points: 1, amount_unit: 10, rounding: "floor"} : e.target.value === "interaction" ? {interactions_required: 10, reward_description: ""} : {amount: 5, currency: "EUR"});}}>
          {["points_per_spend", "interaction", "coupon"].map(k => <option key={k} value={k}>{t(k)}</option>)}
        </select></label>
        {type === "points_per_spend" && <div className="row">
          <label>{t("points")}<input required type="number" min={1} value={config.points} onChange={e => setConfig({...config, points: Number(e.target.value)})} /></label>
          <label>{t("pointsPer")}<input required type="number" min="0.01" step="0.01" value={config.amount_unit} onChange={e => setConfig({...config, amount_unit: Number(e.target.value)})} /></label>
          <label>{t("rounding")}<select value={config.rounding} onChange={e => setConfig({...config, rounding: e.target.value})}>{["floor", "ceil", "round"].map(k => <option key={k} value={k}>{t(k)}</option>)}</select></label>
        </div>}
        {type === "interaction" && <div className="row"><label>{t("interactionsRequired")}<input type="number" min={1} required value={config.interactions_required} onChange={e => setConfig({...config, interactions_required: Number(e.target.value)})} /></label><label>{t("reward")}<input required value={config.reward_description} onChange={e => setConfig({...config, reward_description: e.target.value})} /></label></div>}
        {type === "coupon" && <label>{t("couponAmount")}<input type="number" min="0.01" step="0.01" required value={config.amount} onChange={e => setConfig({...config, amount: Number(e.target.value)})} /></label>}
        <label className="toggle"><input type="checkbox" checked={active} onChange={e => {setActive(e.target.checked); setSelected([]);}} />{t("active")}</label>
      </section>
      <section className="card"><h2>2. {t("passDesign")}</h2><p className="note">{t("designInstructions")}</p><div className="designer-grid"><div>
        <label>{t("passCardTitle")}<input readOnly value={merchantName} aria-describedby="merchant-title-hint" /></label><p className="note" id="merchant-title-hint">{t("merchantTitleHint")}</p>
        {["logo", "hero"].map(kind => <div key={kind}>
          <label>{t(kind === "logo" ? "passLogo" : "heroImage")}<input type="file" accept="image/png,image/jpeg,image/webp" onChange={e => upload(kind, e.target.files[0])} /></label>
          <label>{t(kind === "logo" ? "logoDescription" : "heroDescription")}<input required maxLength={200} value={design[`${kind}_description`]} onChange={e => field(`${kind}_description`, e.target.value)} /></label>
        </div>)}
        <p className="note">{t("assetHint")}</p>
        <div className="row"><label>{t("backgroundColor")}<input type="color" value={/^#[0-9a-f]{6}$/i.test(design.background_color) ? design.background_color : "#373839"} onChange={e => field("background_color", e.target.value)} /></label><label>{t("hexColor")}<input required pattern="#[0-9a-fA-F]{6}" maxLength={7} value={design.background_color} onChange={e => field("background_color", e.target.value)} /></label></div>
        <label>{t("passSubheader")}<input required maxLength={100} value={design.subheader} onChange={e => field("subheader", e.target.value)} /></label>
        <label>{t("pointsLabel")}<input required maxLength={80} value={design.points_label} onChange={e => field("points_label", e.target.value)} /></label>
        <label>{t("memberSinceLabel")}<input required maxLength={80} value={design.member_since_label} onChange={e => field("member_since_label", e.target.value)} /></label>
        <label>{t("barcodeText")}<input required maxLength={200} value={design.barcode_alternate_text} onChange={e => field("barcode_alternate_text", e.target.value)} /></label>
        <label>{t("passLocale")}<select value={design.locale} onChange={e => field("locale", e.target.value)}><option value="es-ES">Español</option><option value="en-US">English</option></select></label>
        <div className="note"><strong>{t("automaticPassData")}</strong><p>{t("automaticPassDataHint")}</p><p>{t("customerSinceHint")}</p></div>
      </div><PassPreview merchantName={merchantName} design={design} logo={images.logo} hero={images.hero} /></div></section>
      <section className="card"><h2>3. {t("customers")}</h2><p className="note">{t("campaignMembersHint")}</p>
        <label>{t("searchCustomers")}<input type="search" value={search} onChange={e => setSearch(e.target.value)} /></label>
        <div className="customer-selection">{customers.filter(c => `${c.name || ""} ${c.customer_code} ${c.email || ""}`.toLowerCase().includes(search.toLowerCase())).map(c => {
          const enrolled = members.some(r => r.customer_id === c.id);
          return <label key={c.id} className="toggle"><input type="checkbox" disabled={enrolled || !active} checked={selected.includes(c.id) || members.some(r => r.customer_id === c.id && r.status === "active")} onChange={e => setSelected(ids => e.target.checked ? [...ids, c.id] : ids.filter(id => id !== c.id))} />{c.name || c.customer_code} {c.name ? `(${c.customer_code})` : ""} {enrolled && <span className="badge">{t("alreadyEnrolled")}</span>}</label>;
        })}</div>
        {members.length > 0 && <table><thead><tr><th>{t("customer")}</th><th>{t("points")}</th><th>{t("status")}</th><th>{t("actions")}</th></tr></thead><tbody>{members.map(row => <tr key={row.id}><td>{row.customer_name}</td><td>{row.points_balance}</td><td>{t(row.status)}</td><td>{row.status === "active" ? <button type="button" className="small ghost" onClick={() => changeMembership(row, "suspended")}>{t("suspendMembership")}</button> : <button type="button" className="small ghost" onClick={() => changeMembership(row, "active")}>{t("resumeMembership")}</button>} {row.status !== "cancelled" && <button type="button" className="small ghost" onClick={() => changeMembership(row, "cancelled")}>{t("cancelMembership")}</button>}</td></tr>)}</tbody></table>}
      </section>
      <section className="card"><h2>4. {t("reviewCampaign")}</h2><p><strong>{name || t("name")}</strong> · {t(type)} · {selected.length} {t("newEnrollments")}</p><p>{t("backgroundColor")}: {design.background_color} · {t("passLogo")}: {t(design.logo_asset_id ? "ready" : "missing")} · {t("heroImage")}: {t(design.hero_asset_id ? "ready" : "missing")}</p>
        <PassPreview merchantName={merchantName} design={design} logo={images.logo} hero={images.hero} />
        <label className="toggle"><input type="checkbox" required checked={reviewed} onChange={e => {e.stopPropagation(); setReviewed(e.target.checked);}} />{t("confirmDesign")}</label>
        <div className="btns"><button type="submit">{t(campaign ? "save" : "create")}</button><button type="button" className="ghost" onClick={onCancel}>{t("cancel")}</button></div>
      </section>
    </fieldset>
  </form>;
}
