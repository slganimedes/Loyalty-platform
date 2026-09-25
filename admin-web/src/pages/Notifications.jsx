import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import MerchantPicker from "../components/MerchantPicker";
import NotificationFields, { notificationTypes } from "../components/NotificationFields";
import { useApp } from "../context/AppContext";

const statuses = ["queued", "sending", "success", "partial", "failed", "skipped", "unknown"];
const targetLabel = type => ({campaign: "targetCampaign", pass: "targetPass", payment: "targetPayment"}[type]);

function NotificationHistory({ merchantId, campaigns, revision }) {
  const { t, lang } = useApp();
  const [filters, setFilters] = useState({ campaign_id: "", date_from: "", date_to: "", status: "", offset: 0 });
  const [data, setData] = useState({ items: [], total: 0 });
  const [err, setErr] = useState("");
  const [detail, setDetail] = useState(null);
  const dialog = useRef(null);
  const filterKey = JSON.stringify(filters);
  useEffect(() => {
    let active = true;
    let timer;
    const refresh = async () => {
      try {
        const result = await api.notificationHistory(merchantId, JSON.parse(filterKey));
        if (active) { setData(result); setErr(""); }
      } catch (e) { if (active) setErr(e.message); }
      if (active) timer = setTimeout(refresh, 4000);
    };
    refresh();
    return () => { active = false; clearTimeout(timer); };
  }, [merchantId, filterKey, revision]);
  const filter = (key, value) => setFilters(prev => ({ ...prev, [key]: value, offset: 0 }));
  const show = async id => {
    try { setDetail(await api.notificationDetail(merchantId, id)); dialog.current?.showModal(); }
    catch (e) { setErr(e.message); }
  };
  return <section className="card" aria-labelledby="notification-history-heading">
    <h2 id="notification-history-heading">{t("notificationHistory")}</h2>
    <p className="note">{t("deliveryHint")}</p>
    <div className="row">
      <div><label htmlFor="notification-history-campaign">{t("targetCampaign")}</label><select id="notification-history-campaign" value={filters.campaign_id} onChange={e => filter("campaign_id", e.target.value)}><option value="">{t("allCampaigns")}</option>{campaigns.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></div>
      <div><label htmlFor="notification-from">{t("fromDate")}</label><input id="notification-from" type="date" value={filters.date_from} onChange={e => filter("date_from", e.target.value)} /></div>
      <div><label htmlFor="notification-to">{t("toDate")}</label><input id="notification-to" type="date" min={filters.date_from || undefined} value={filters.date_to} onChange={e => filter("date_to", e.target.value)} /></div>
      <div><label htmlFor="notification-history-status">{t("status")}</label><select id="notification-history-status" value={filters.status} onChange={e => filter("status", e.target.value)}><option value="">{t("allStatuses")}</option>{statuses.map(s => <option key={s} value={s}>{t(`notificationStatus_${s}`)}</option>)}</select></div>
    </div>
    {err && <p className="error" role="alert">{t(err)}</p>}
    <div className="notification-table"><table><thead><tr>{["date", "targetType", "targetCampaign", "targetPass", "notificationTitle", "createdBy", "status"].map(key => <th key={key}>{t(key)}</th>)}</tr></thead>
      <tbody>{data.items.map(row => <tr key={row.id}>
        <td>{new Date(row.created_at).toLocaleString(lang)}</td><td>{t(targetLabel(row.target_type))}</td><td>{row.campaign_name || "—"}</td><td title={row.pass_id || ""}>{row.pass_id ? row.pass_id.slice(0, 8) : "—"}</td>
        <td><button className="ghost small" onClick={() => show(row.id)}>{row.title}</button></td><td>{row.sender_name}</td><td><span className={`badge notification-${row.status}`}>{t(`notificationStatus_${row.status}`)}</span></td>
      </tr>)}</tbody></table></div>
    {!data.items.length && <p className="note">{t("noNotificationHistory")}</p>}
    <div className="btns"><button className="ghost small" disabled={!filters.offset} onClick={() => setFilters({...filters, offset: Math.max(0, filters.offset - 25)})}>{t("previousPage")}</button><span>{data.total ? filters.offset + 1 : 0}–{Math.min(filters.offset + 25, data.total)} / {data.total}</span><button className="ghost small" disabled={filters.offset + 25 >= data.total} onClick={() => setFilters({...filters, offset: filters.offset + 25})}>{t("nextPage")}</button></div>
    <dialog ref={dialog} className="notification-dialog" aria-labelledby="notification-detail-heading">
      <h2 id="notification-detail-heading">{t("notificationDetails")}</h2>
      {detail && <><h3>{detail.title}</h3><p className="notification-text">{detail.message}</p><p>{t("recipientCount")}: {detail.estimated_recipients} · {t("affectedPasses")}: {detail.pass_count}</p>
        {detail.reason && <p>{t(detail.reason)}</p>}
        <h3>{t("notificationCounts")}</h3>
        <ul>{Object.entries(detail.delivery_counts).map(([status, count]) => <li key={status}>{t(`notificationStatus_${status === "pending" ? "queued" : status}`)}: {count}</li>)}</ul>
        {detail.deliveries.map((d, i) => <details key={i}><summary>{d.platform === "apple" ? "Apple Wallet" : "Google Wallet"} · {d.pass_id.slice(0, 8)} · {t(`notificationStatus_${d.status === "pending" ? "queued" : d.status}`)}</summary><p>{t(d.reason || "")}</p><strong>{d.payload.title}</strong><p className="notification-text">{d.payload.message}</p></details>)}
      </>}
      <div className="btns"><button onClick={() => dialog.current.close()}>{t("closeNotification")}</button></div>
    </dialog>
  </section>;
}

function NotificationCenter({ merchantId }) {
  const { t } = useApp();
  const [campaigns, setCampaigns] = useState([]);
  const [targetType, setTargetType] = useState("campaign");
  const [selected, setSelected] = useState(null);
  const [search, setSearch] = useState("");
  const [searchResult, setSearchResult] = useState({ items: [], total: 0 });
  const [searching, setSearching] = useState(false);
  const [content, setContent] = useState({ title: "", message: "", type: "general_update", preview_text: "", url: "" });
  const [preview, setPreview] = useState(null);
  const [previewError, setPreviewError] = useState("");
  const [err, setErr] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [massConfirmed, setMassConfirmed] = useState(false);
  const [revision, setRevision] = useState(0);
  const dialog = useRef(null);
  const submitting = useRef(false);
  const pending = useRef(null);
  const draft = selected ? { ...content, url: content.url || null, target_type: targetType,
    campaign_id: targetType === "campaign" ? selected.id : null, pass_id: targetType === "pass" ? selected.id : null } : null;
  const draftKey = JSON.stringify(draft);

  useEffect(() => {
    let active = true;
    api.notificationCampaigns(merchantId).then(data => { if (active) setCampaigns(data); }).catch(e => { if (active) setErr(e.message); });
    return () => { active = false; };
  }, [merchantId, revision]);
  useEffect(() => {
    if (targetType !== "pass") return;
    let active = true;
    setSearching(true);
    const timer = setTimeout(() => api.notificationPasses(merchantId, search).then(data => { if (active) setSearchResult(data); }).catch(e => { if (active) setErr(e.message); }).finally(() => { if (active) setSearching(false); }), 250);
    return () => { active = false; clearTimeout(timer); };
  }, [merchantId, search, targetType]);
  useEffect(() => {
    let active = true;
    setPreview(null); setPreviewError("");
    const body = JSON.parse(draftKey);
    if (!body?.title.trim() || !body?.message.trim()) return;
    const timer = setTimeout(() => api.previewNotification(merchantId, body).then(data => { if (active) setPreview({ ...data, draftKey }); }).catch(e => { if (active) setPreviewError(e.message); }), 300);
    return () => { active = false; clearTimeout(timer); };
  }, [merchantId, draftKey, revision]);

  const suggestion = (target, type) => {
    const campaignType = target?.campaign_type || target?.type;
    if (type === "new_reward") return t("suggestionReward");
    if (type === "coupon_available" || campaignType === "coupon" && type === "general_update") return t("suggestionCoupon");
    if (type === "coupon_expiring") return t("suggestionExpiring");
    if (campaignType === "interaction" && type === "general_update") return t(target?.stamps_remaining === 1 ? "suggestionOneVisit" : "suggestionStamps");
    if (type === "points_earned" || campaignType === "points_per_spend") return t("suggestionPoints");
    return t("suggestionGeneral");
  };
  const choose = target => {
    setSelected(target); setPreview(null); setNotice(""); setErr("");
    if (target) setContent(prev => ({ ...prev, title: target.name || target.campaign_name,
      message: suggestion(target, prev.type), url: "", preview_text: "" }));
  };
  const ready = preview && preview.draftKey === draftKey && preview.estimated_recipients > 0;
  const confirm = e => {
    e.preventDefault();
    if (!ready) return;
    setErr(""); setMassConfirmed(false); dialog.current.showModal();
  };
  const send = async () => {
    if (submitting.current || !ready) return;
    submitting.current = true; setBusy(true); setErr("");
    const body = { ...draft, expected_recipients: preview.estimated_recipients,
      audience_revision: preview.audience_revision, confirm_mass_send: massConfirmed };
    const fingerprint = JSON.stringify(body);
    if (pending.current?.fingerprint !== fingerprint) pending.current = { fingerprint, id: crypto.randomUUID() };
    try {
      await api.sendNotification(merchantId, { ...body, request_id: pending.current.id });
      pending.current = null; dialog.current?.close(); setNotice(t("notificationQueued")); setRevision(r => r + 1);
    } catch (e) {
      setErr(e.message); dialog.current?.close(); setRevision(r => r + 1);
    } finally { submitting.current = false; setBusy(false); }
  };
  return <>
    <form onSubmit={confirm}>
      <section className="card"><h2>{t("notificationTarget")}</h2>
        <div className="notification-target-options">{["campaign", "pass"].map(type => <label key={type} className="toggle"><input type="radio" name="notification-target" checked={targetType === type} onChange={() => { setTargetType(type); choose(null); }} />{t(targetLabel(type))}</label>)}</div>
        {targetType === "campaign" ? <><label htmlFor="notification-campaign">{t("targetCampaign")}</label><select required id="notification-campaign" value={selected?.id || ""} onChange={e => choose(campaigns.find(c => c.id === e.target.value) || null)}><option value="">{t("selectCampaignNotification")}</option>{campaigns.map(c => <option key={c.id} value={c.id}>{c.name} ({c.estimated_recipients})</option>)}</select></> : <>
          <label htmlFor="notification-search">{t("searchNotificationPass")}</label><input id="notification-search" type="search" maxLength={200} value={search} onChange={e => setSearch(e.target.value)} />
          <label htmlFor="notification-pass">{t("targetPass")}</label><select id="notification-pass" required disabled={searching} value={selected?.id || ""} onChange={e => choose(searchResult.items.find(p => p.id === e.target.value) || null)}><option value="">{t(searching ? "loading" : "selectPassNotification")}</option>
            {selected && !searchResult.items.some(p => p.id === selected.id) && <option value={selected.id}>{selected.customer_name} · {selected.campaign_name}</option>}
            {searchResult.items.map(p => <option key={p.id} value={p.id}>{p.customer_name} · {p.campaign_name} · {p.platform === "apple" ? "Apple Wallet" : "Google Wallet"} · {p.id.slice(0, 8)}</option>)}</select>
          {searchResult.total > searchResult.items.length && <p className="note">{t("moreSearchResults")}</p>}
        </>}
        {selected && <div className="notification-summary">
          <strong>{selected.name || selected.campaign_name}</strong>
          {targetType === "pass" && <><span>{selected.customer_name}</span><span>{t("balance")}: {selected.points_balance}</span>{selected.campaign_type === "interaction" && <><span>{t("stampCount")}: {selected.stamp_count}</span><span>{t("stampsRemaining")}: {selected.stamps_remaining}</span><span>{t("rewardsEarned")}: {selected.rewards_earned} · {selected.reward_name}</span></>}</>}
          <span>{t("recipientCount")}: {preview?.estimated_recipients ?? selected.estimated_recipients ?? 1} · {t("affectedPasses")}: {preview?.pass_count ?? selected.pass_count ?? 1}</span>
        </div>}
        {selected?.pass_count === 0 && <p className="notification-warning" role="status">{t("no_passes")}</p>}
      </section>
      {selected && <><section className="card"><h2>{t("notificationCompose")}</h2>
        <div className="row"><div><label htmlFor="notification-type">{t("notificationType")}</label><select id="notification-type" value={content.type} onChange={e => setContent(prev => ({...prev, type: e.target.value, message: e.target.value === "custom" ? prev.message : suggestion(selected, e.target.value)}))}>{notificationTypes.map(type => <option key={type} value={type}>{t(type)}</option>)}</select></div></div>
        <NotificationFields value={content} onChange={setContent} disabled={busy} />
        <div className="btns"><button type="button" className="ghost small" onClick={() => setContent(prev => ({...prev, message: suggestion(selected, prev.type)}))}>{t("useSuggestion")}</button></div>
      </section>
      <section className="card"><h2>{t("notificationPreview")}</h2><p className="note">{t("notificationPreviewHint")}</p>
        {previewError && <p role="alert" className="error">{previewError}</p>}
        {!preview && !previewError && <p className="note">{t("loading")}</p>}
        {preview && <><div className="notification-previews">{["Apple Wallet", "Google Wallet"].map((provider, i) => <article className={`wallet-notification wallet-notification-${i}`} key={provider} aria-label={provider}>
          <div className="wallet-notification-provider">{provider}</div><h3>{preview.sample.title}</h3><p className="notification-text">{preview.sample.message}</p>{preview.sample.preview_text && <p>{preview.sample.preview_text}</p>}{preview.sample.url && <a href={preview.sample.url} target="_blank" rel="noreferrer">{preview.sample.url}</a>}<p className="note">{t("recipientCount")}: {preview.estimated_recipients}</p>
        </article>)}</div>{preview.warnings.map(w => <p key={w} className="notification-warning">{t(w)}</p>)}</>}
        <div className="btns"><button disabled={!ready || busy}>{t("sendNotification")}</button></div>
      </section></>}
    </form>
    {err && <p role="alert" className="error">{t(err)}</p>}{notice && <p role="status">{notice}</p>}
    <dialog ref={dialog} className="notification-dialog" aria-labelledby="notification-confirm-heading" onCancel={e => { if (busy) e.preventDefault(); }}>
      <h2 id="notification-confirm-heading">{t("sendNotification")}</h2><p>{t("confirmNotification").replace("{count}", preview?.estimated_recipients ?? 0)}</p>
      <strong>{content.title}</strong><p className="notification-text">{preview?.sample.message}</p>
      {preview?.warnings.includes("mass_send") && <label className="toggle"><input type="checkbox" checked={massConfirmed} disabled={busy} onChange={e => setMassConfirmed(e.target.checked)} />{t("confirmMassSend")}</label>}
      <div className="btns"><button className="ghost" disabled={busy} onClick={() => dialog.current.close()}>{t("cancel")}</button><button disabled={busy || !ready || preview?.warnings.includes("mass_send") && !massConfirmed} onClick={send}>{t("sendNotification")}</button></div>
    </dialog>
    <NotificationHistory merchantId={merchantId} campaigns={campaigns} revision={revision} />
  </>;
}

export default function Notifications() {
  const { t, merchantId } = useApp();
  return <><h1>{t("notifications")}</h1><p className="note">{t("notificationIntro")}</p><MerchantPicker />{merchantId && <NotificationCenter key={merchantId} merchantId={merchantId} />}</>;
}
