import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { useApp } from "./context/AppContext";
import Login from "./pages/Login";
import Merchants from "./pages/Merchants";
import Customers from "./pages/Customers";
import Campaigns from "./pages/Campaigns";
import Coupons from "./pages/Coupons";
import Transactions from "./pages/Transactions";
import WalletConfig from "./pages/WalletConfig";
import Passes from "./pages/Passes";

function RequireAuth({ children }) {
  const { user, ready, t } = useApp();
  if (!ready) return <p>{t("loading")}</p>;
  return user ? children : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="/merchants" replace />} />
        <Route path="/merchants" element={<Merchants />} />
        <Route path="/customers" element={<Customers />} />
        <Route path="/campaigns" element={<Campaigns />} />
        <Route path="/coupons" element={<Coupons />} />
        <Route path="/wallet" element={<WalletConfig />} />
        <Route path="/passes" element={<Passes />} />
        <Route path="/transactions" element={<Transactions />} />
      </Route>
      <Route path="*" element={<Navigate to="/merchants" replace />} />
    </Routes>
  );
}
