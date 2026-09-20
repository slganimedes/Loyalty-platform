// Minimal API client. Base URL defaults to same-origin /api (works with the
// Vite dev proxy and in production behind Cloudflare/Caddy).
const BASE = import.meta.env.VITE_API_BASE || "/api/v1";

async function request(path, { method = "GET", body } = {}) {
  const res = await fetch(BASE + path, {
    method,
    headers: { "Content-Type": "application/json", ...(sessionStorage.getItem("token") ? {Authorization: `Bearer ${sessionStorage.getItem("token")}`} : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    if (res.status === 401 && path !== "/auth/login") window.dispatchEvent(new Event("session-expired"));
    const error = await res.json().catch(() => ({}));
    throw new Error(Array.isArray(error.detail) ? error.detail.map(e => `${e.loc.slice(1).join(".")}: ${e.msg}`).join("; ") : error.detail || res.statusText);
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : res.text();
}

export const api = {
  listPasses: (mid) => request(`/merchants/${mid}/passes`),
  assignPass: (cid, body) => request(`/customers/${cid}/passes`, { method: "POST", body }),
  passLink: (cid, pid) => request(`/customers/${cid}/passes/${pid}/link`, { method: "POST" }),
  deleteCustomer: (cid) => request(`/customers/${cid}`, { method: "DELETE" }),
  login: (body) => request("/auth/login", { method: "POST", body }),
  logout: () => request("/auth/logout", { method: "POST" }),
  me: () => request("/users/me"),
  language: (language) => request("/users/me", { method: "PATCH", body: { language } }),
  health: async () => { const r = await fetch("/health"); if (!r.ok) throw new Error("API unavailable"); return r.json(); },
  getPasses: (cid) => request(`/customers/${cid}/passes`),
  refreshPasses: (cid) => request(`/customers/${cid}/passes/refresh`, { method: "POST" }),
  deletePass: (cid, pid) => request(`/customers/${cid}/passes/${pid}`, { method: "DELETE" }),
  deleteCampaign: (mid, cid) => request(`/merchants/${mid}/campaigns/${cid}`, { method: "DELETE" }),
  ingest: (body) => request("/transactions", { method: "POST", body }),

  // Merchants
  listMerchants: () => request("/merchants"),
  createMerchant: (data) => request("/merchants", { method: "POST", body: data }),
  updateMerchant: (id, data) => request(`/merchants/${id}`, { method: "PATCH", body: data }),

  // Customers
  listCustomers: (mid) => request(`/merchants/${mid}/customers`),
  enrollCustomer: (mid, data) => request(`/merchants/${mid}/customers`, { method: "POST", body: data }),
  getMovements: (cid) => request(`/customers/${cid}/movements`),

  // Campaigns
  listCampaigns: (mid) => request(`/merchants/${mid}/campaigns`),
  createCampaign: (mid, data) => request(`/merchants/${mid}/campaigns`, { method: "POST", body: data }),

  // Coupons
  listCoupons: (mid) => request(`/merchants/${mid}/coupons`),
  issueCoupon: (mid, data) => request(`/merchants/${mid}/coupons`, { method: "POST", body: data }),

  // Wallet config
  getWallet: () => request("/settings/wallet"),
  setApple: (data) => request("/settings/wallet/apple", { method: "PUT", body: data }),
  setGoogle: (data) => request("/settings/wallet/google", { method: "PUT", body: data }),
};
