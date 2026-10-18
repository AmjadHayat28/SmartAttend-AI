import { LogOut, Menu, Moon, Sun } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useTheme } from "../../context/ThemeContext";
import { useAuth } from "../../hooks/useAuth";
import { ROLE_LABELS } from "../../types/auth";
import { initials } from "../../utils/format";

export function Topbar({ onMenu }: { onMenu: () => void }) {
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const navigate = useNavigate();
  if (!user) return null;

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-slate-200 bg-white/90 px-4 backdrop-blur sm:px-6 dark:border-slate-800 dark:bg-slate-950/90">
      <button className="rounded-lg p-2 text-slate-600 hover:bg-slate-100 lg:hidden dark:text-slate-300 dark:hover:bg-slate-800" onClick={onMenu} aria-label="Open menu">
        <Menu className="h-5 w-5" />
      </button>
      <div className="min-w-0 flex-1">
        {user.department_name && (
          <p className="truncate text-sm font-medium text-slate-700 dark:text-slate-300">{user.department_name}</p>
        )}
      </div>
      <button
        onClick={toggle}
        className="rounded-lg p-2 text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
        aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
      >
        {theme === "dark" ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
      </button>
      <div className="flex items-center gap-3 border-l border-slate-200 pl-3 dark:border-slate-800">
        <span className="grid h-9 w-9 place-items-center rounded-full bg-brand-100 text-sm font-semibold text-brand-800 dark:bg-brand-900 dark:text-brand-100">
          {initials(user.full_name) || "U"}
        </span>
        <div className="hidden leading-tight sm:block">
          <p className="text-sm font-medium text-slate-900 dark:text-white">{user.full_name}</p>
          <p className="text-xs text-slate-500 dark:text-slate-400">{ROLE_LABELS[user.role]}</p>
        </div>
        <button
          onClick={() => {
            logout();
            navigate("/login", { replace: true });
          }}
          className="rounded-lg p-2 text-slate-600 hover:bg-slate-100 hover:text-red-600 dark:text-slate-300 dark:hover:bg-slate-800"
          aria-label="Sign out"
          title="Sign out"
        >
          <LogOut className="h-5 w-5" />
        </button>
      </div>
    </header>
  );
}
