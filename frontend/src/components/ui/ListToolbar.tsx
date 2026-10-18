import { Search } from "lucide-react";
import type { ReactNode } from "react";

const controlClass =
  "h-9 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-800 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200";

export function ListToolbar({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-5 py-3 dark:border-slate-800">{children}</div>;
}

export function SearchBox({ value, onChange, placeholder = "Search…", className = "w-full sm:w-64" }: { value: string; onChange: (v: string) => void; placeholder?: string; className?: string }) {
  return (
    <div className={`relative ${className}`}>
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
      <input type="search" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} aria-label={placeholder} className={`${controlClass} w-full pl-8`} />
    </div>
  );
}

interface FilterSelectProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string | number; label: string }[];
  allLabel?: string;
  disabled?: boolean;
}

export function FilterSelect({ label, value, onChange, options, allLabel = "All", disabled }: FilterSelectProps) {
  return (
    <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} className={`${controlClass} max-w-[14rem] disabled:opacity-50`}>
      <option value="">
        {label}: {allLabel}
      </option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export const STATUS_OPTIONS = [
  { value: "active", label: "Active" },
  { value: "pending", label: "Pending" },
  { value: "suspended", label: "Suspended" },
  { value: "rejected", label: "Rejected" },
];

export const ACTIVE_OPTIONS = [
  { value: "true", label: "Active" },
  { value: "false", label: "Inactive" },
];
