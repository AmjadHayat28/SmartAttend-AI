import { CalendarCheck, ScanFace, ShieldCheck } from "lucide-react";
import { Outlet } from "react-router-dom";
import { Logo } from "../components/layout/Logo";

const FEATURES = [
  { icon: ScanFace, text: "Attendance from a single classroom photo" },
  { icon: ShieldCheck, text: "Department-isolated, role-based access" },
  { icon: CalendarCheck, text: "Subject-wise reports and Excel export" },
];

export function AuthLayout() {
  return (
    <div className="grid min-h-screen lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <section className="relative hidden flex-col justify-between overflow-hidden bg-brand-900 p-10 text-white lg:flex">
        <div className="absolute -right-24 -top-24 h-80 w-80 rounded-full bg-brand-700/40" aria-hidden />
        <div className="absolute -bottom-32 -left-16 h-96 w-96 rounded-full bg-brand-800/60" aria-hidden />
        <Logo inverted className="relative" />
        <div className="relative">
          <h1 className="text-3xl font-semibold leading-tight">SmartClass AI Attendance Management System</h1>
          <ul className="mt-8 space-y-4">
            {FEATURES.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-center gap-3 text-brand-100">
                <span className="grid h-9 w-9 place-items-center rounded-lg bg-white/10">
                  <Icon className="h-5 w-5" />
                </span>
                {text}
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-sm text-brand-200">Secure access for administrators, HODs, teachers and students.</p>
      </section>
      <section className="flex items-center justify-center px-4 py-10 sm:px-8">
        <div className="w-full max-w-md">
          <Logo className="mb-8 lg:hidden" />
          <Outlet />
        </div>
      </section>
    </div>
  );
}
