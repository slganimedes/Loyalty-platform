import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useApp } from "../context/AppContext";

// Shared merchant selector used by Customers / Campaigns / Coupons pages.
export default function MerchantPicker() {
  const { t, merchantId, selectMerchant } = useApp();
  const [merchants, setMerchants] = useState([]);

  useEffect(() => {
    api.listMerchants().then(setMerchants).catch(() => setMerchants([]));
  }, []);

  return (
    <div className="card">
      <label>{t("merchant")}</label>
      <select aria-label={t("merchant")} value={merchantId} onChange={(e) => selectMerchant(e.target.value)}>
        <option value="">{t("selectMerchantFirst")}</option>
        {merchants.map((m) => (
          <option key={m.id} value={m.id}>
            {m.name}
          </option>
        ))}
      </select>
    </div>
  );
}
