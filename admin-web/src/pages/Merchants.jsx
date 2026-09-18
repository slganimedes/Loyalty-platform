import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { useApp } from "../context/AppContext";
import { readLogo } from "../api/logo";

export default function Merchants() {
  const { t, selectMerchant, user } = useApp();
  const [merchants, setMerchants] = useState([]);
  const [name, setName] = useState("");
  const [color, setColor] = useState("#C81E1E");
  const [logo, setLogo] = useState(undefined);
  const [preview, setPreview] = useState("");
  const [saving, setSaving] = useState(false);
  const [reading, setReading] = useState(false);
  const fileInput = useRef(null);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState(null);
  const [err, setErr] = useState("");

  const load = () => {
    setLoading(true);
    api.listMerchants().then(setMerchants).catch((e) => setErr(String(e))).finally(() => setLoading(false));
  };
  useEffect(load, []);

  const upload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setReading(true); setErr("");
    try {
      const image = await readLogo(file);
      setLogo(image.base64); setPreview(image.preview);
    } catch (e) { setErr(t(e.message)); fileInput.current.value = ""; }
    finally { setReading(false); }
  };

  const create = async (e) => {
    e.preventDefault();
    if (saving || reading) return;
    setSaving(true);
    setErr("");
    try {
      const body = { name, pass_color: color, ...(logo !== undefined ? { logo_base64: logo } : {}) };
      if (editing) await api.updateMerchant(editing, body);
      else await api.createMerchant(body);
      setEditing(null);
      setName(""); setColor("#C81E1E"); setLogo(undefined); setPreview("");
      fileInput.current.value = "";
      load();
    } catch (e) { setErr(String(e)); } finally { setSaving(false); }
  };

  const toggleStatus = async (m) => {
    try { await api.updateMerchant(m.id, { status: m.status === "active" ? "inactive" : "active" }); load(); } catch (e) { setErr(e.message); }
  };

  return (
    <>
      <h1>{t("merchants")}</h1>

      {(user.role === "super_admin" || editing) && <div className="card">
        <h2>{t(editing ? "edit" : "newMerchant")}</h2>
        <form onSubmit={create}>
          <div className="row">
            <div>
              <label>{t("name")}</label>
              <input aria-label={t("name")} value={name} onChange={(e) => setName(e.target.value)} required />
            </div>
            <div>
              <label>{t("color")}</label>
              <input aria-label={t("color")} type="color" value={color} onChange={(e) => setColor(e.target.value)} />
            </div>
            <div>
              <label>{t("logo")}</label>
              <input ref={fileInput} aria-label={t("logo")} type="file" accept="image/png,image/jpeg,image/webp" disabled={saving || reading} onChange={upload} />
              <p className="note">{t("logoHint")}</p>
              {preview && <><img className="logo-preview" src={preview} alt={t("logoPreview")} /><button type="button" className="ghost small" disabled={saving || reading} onClick={() => { setLogo(null); setPreview(""); fileInput.current.value = ""; }}>{t("removeLogo")}</button></>}
            </div>
          </div>
          <div className="btns">
            <button type="submit" disabled={saving || reading}>{t(reading ? "loading" : editing ? "save" : "create")}</button>
            <button type="button" className="ghost" onClick={load}>{t("refresh")}</button>
          </div>
        </form>
      </div>}

      <div className="card">
        <h2>{t("merchants")}</h2>
        {err && <p role="alert" className="error">{err}</p>}
        {loading ? <p className="note">{t("loading")}</p> : (
          <table>
            <thead>
              <tr>
                <th>{t("name")}</th><th>{t("status")}</th><th>{t("id")}</th><th>{t("actions")}</th>
              </tr>
            </thead>
            <tbody>
              {merchants.length === 0 && <tr><td colSpan="4" className="note">{t("noData")}</td></tr>}
              {merchants.map((m) => (
                <tr key={m.id}>
                  <td>{m.logo_url ? <img className="merchant-logo" src={m.logo_url} alt={`${t("logo")} ${m.name}`} /> : <span className="pill" style={{ background: m.pass_color }} />}{m.name}</td>
                  <td><span className={"badge " + m.status}>{t(m.status)}</span></td>
                  <td className="note">{m.id.slice(0, 8)}…</td>
                  <td>
                    <button className="small ghost" onClick={() => selectMerchant(m.id)}>{t("select")}</button>{" "}
                    <button className="small ghost" disabled={saving || reading} onClick={() => { setEditing(m.id); setName(m.name); setColor(m.pass_color); setLogo(undefined); setPreview(m.logo_url || ""); setErr(""); if (fileInput.current) fileInput.current.value = ""; }}>{t("edit")}</button>{" "}
                    <button className="small" onClick={() => toggleStatus(m)}>{t("status")}</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
