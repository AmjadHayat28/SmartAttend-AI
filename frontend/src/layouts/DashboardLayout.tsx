import { useState } from "react";
import { Outlet } from "react-router-dom";
import { Sidebar } from "../components/layout/Sidebar";
import { Topbar } from "../components/layout/Topbar";
import { useAuth } from "../hooks/useAuth";

export function DashboardLayout() {
  const { user } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  if (!user) return null;

  return (
    <div className="min-h-screen">
      <Sidebar role={user.role} open={menuOpen} onClose={() => setMenuOpen(false)} />
      <div className="lg:pl-64">
        <Topbar onMenu={() => setMenuOpen(true)} />
        <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
