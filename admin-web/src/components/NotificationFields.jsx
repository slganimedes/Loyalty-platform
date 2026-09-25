import { useRef } from "react";
import { useApp } from "../context/AppContext";

export const notificationTypes = ["general_update", "new_reward", "points_earned", "coupon_available", "coupon_expiring", "custom"];
export const placeholders = ["customerName", "campaignName", "amount", "pointsEarned", "currentPoints", "currentStamps", "rewardName"];

export default function NotificationFields({ value, onChange, payment = false, disabled = false }) {
  const { t } = useApp();
  const message = useRef(null);
  const update = (key, text) => onChange({ ...value, [key]: text });
  const insert = key => {
    const input = message.current;
    const start = input.selectionStart ?? value.message.length;
    const end = input.selectionEnd ?? start;
    const token = `{{${key}}}`;
    update("message", value.message.slice(0, start) + token + value.message.slice(end));
    requestAnimationFrame(() => { input.focus(); input.setSelectionRange(start + token.length, start + token.length); });
  };
  return <fieldset className="notification-fields" disabled={disabled}>
    <label htmlFor="notification-title">{t("notificationTitle")}</label>
    <input id="notification-title" required maxLength={200} value={value.title} onChange={e => update("title", e.target.value)} />
    <label htmlFor="notification-message">{t("notificationMessage")}</label>
    <textarea ref={message} id="notification-message" required rows={4} maxLength={2000} value={value.message} onChange={e => update("message", e.target.value)} />
    <p className="note">{t(payment ? "paymentNotificationHint" : "placeholderHint")}</p>
    <div className="placeholder-buttons" role="group" aria-label={t("insertPlaceholder")}>
      {placeholders.filter(key => payment || !["amount", "pointsEarned"].includes(key)).map(key => <button key={key} type="button" className="ghost small" onClick={() => insert(key)}>{t(`ph_${key}`)}</button>)}
    </div>
    {!payment && <div className="row">
      <div><label htmlFor="notification-url">{t("notificationUrl")}</label><input id="notification-url" type="url" maxLength={2048} value={value.url || ""} onChange={e => update("url", e.target.value)} /></div>
      <div><label htmlFor="notification-preview-text">{t("notificationPreviewText")}</label><input id="notification-preview-text" maxLength={200} value={value.preview_text || ""} onChange={e => update("preview_text", e.target.value)} /></div>
    </div>}
  </fieldset>;
}
