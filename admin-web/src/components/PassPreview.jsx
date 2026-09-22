import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { useApp } from "../context/AppContext";
import { translations } from "../i18n";

export default function PassPreview({ merchantName, design, logo, hero }) {
  const { t } = useApp();
  const passT = key => translations[design.locale === "en-US" ? "en" : "es"][key] || t(key);
  const [qr, setQr] = useState("");
  useEffect(() => { QRCode.toDataURL("preview-example-not-a-valid-membership", {width: 160, margin: 2}).then(setQr); }, []);
  const color = /^#[0-9a-f]{6}$/i.test(design.background_color) ? design.background_color : "#373839";
  const rgb = color.slice(1).match(/../g).map(c => parseInt(c, 16) / 255).map(c => c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4);
  const light = rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722;
  return <figure className="pass-preview" aria-label={t("passPreview")}>
    <div className="wallet-card" style={{background: color, color: light > .179 ? "#000" : "#fff"}}>
      <div className="wallet-brand">{logo && <img src={logo} alt={design.logo_description} />}<strong>{merchantName}</strong></div>
      <small>{design.subheader}</small><h3>{passT("exampleCustomer")}</h3>
      <div className="wallet-fields"><div><small>{design.points_label || passT("points")}</small><strong>320</strong></div><div><small>{design.member_since_label || passT("memberSince")}</small><strong>{passT("exampleMonth")}</strong></div></div>
      {qr && <img className="preview-barcode" src={qr} alt={t("exampleQr")} />}
      <p className="preview-barcode-text">{design.barcode_alternate_text || passT("barcodeDefault")}</p>
      {hero && <img className="preview-hero" src={hero} alt={design.hero_description} />}
    </div>
    <figcaption>{t("previewDisclaimer")}</figcaption>
  </figure>;
}
