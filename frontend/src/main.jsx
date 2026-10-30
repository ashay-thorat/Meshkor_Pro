import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";

import "./styles.css";
import { AuthProvider, LoginPage, useAuth } from "./auth.jsx";
import Overview from "./pages/Overview.jsx";
import DrugDetail from "./pages/DrugDetail.jsx";
import Hospitals from "./pages/Hospitals.jsx";
import HospitalDetail from "./pages/HospitalDetail.jsx";
import Rates from "./pages/Rates.jsx";
import Quality from "./pages/Quality.jsx";
import Method from "./pages/Method.jsx";

const ROLE_TEXT = { admin: "Admin", reviewer: "Reviewer", viewer: "Viewer" };

function Shell() {
  const { user, checked, logout } = useAuth();
  if (!checked) return <div className="note">Loading…</div>;
  if (!user) return <LoginPage />;
  return (
    <div className="shell">
      <header className="top">
        <div className="brand">
          <span className="mark">Rx</span>
          <div>
            <div className="title">Infusion Drug Markup Audit</div>
            <div className="sub">Ohio hospitals · price per billing unit vs Medicare ASP+6%</div>
          </div>
        </div>
        <nav>
          <NavLink to="/" end>Drugs</NavLink>
          <NavLink to="/hospitals">Hospitals</NavLink>
          <NavLink to="/rates">All rates</NavLink>
          <NavLink to="/quality">Data quality</NavLink>
          <NavLink to="/method">Method</NavLink>
        </nav>
        <div className="usermenu">
          <span>{user.name}</span>
          <span className={`pill role-${user.role}`}>{ROLE_TEXT[user.role] || user.role}</span>
          {user.is_admin && <a href="/admin/" target="_blank" rel="noreferrer">Users</a>}
          <button onClick={logout}>Sign out</button>
        </div>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/drugs/:hcpcs" element={<DrugDetail />} />
          <Route path="/hospitals" element={<Hospitals />} />
          <Route path="/hospitals/:key" element={<HospitalDetail />} />
          <Route path="/rates" element={<Rates />} />
          <Route path="/quality" element={<Quality />} />
          <Route path="/method" element={<Method />} />
        </Routes>
      </main>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <BrowserRouter><AuthProvider><Shell /></AuthProvider></BrowserRouter>
);
