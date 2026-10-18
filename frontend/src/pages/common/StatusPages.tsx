import { Link } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";
import { ROLE_HOME } from "../../types/auth";

function FullPageMessage({ code, title, text }: { code: string; title: string; text: string }) {
  const { user } = useAuth();
  return (
    <div className="grid min-h-screen place-items-center px-4">
      <div className="text-center">
        <p className="text-sm font-semibold text-brand-700 dark:text-brand-200">{code}</p>
        <h1 className="mt-2 text-3xl font-semibold text-slate-900 dark:text-white">{title}</h1>
        <p className="mt-2 text-slate-500 dark:text-slate-400">{text}</p>
        <Link to={user ? ROLE_HOME[user.role] : "/login"} className="mt-6 inline-block rounded-lg bg-brand-700 px-4 py-2 text-sm font-medium text-white hover:bg-brand-800">
          Go to {user ? "dashboard" : "sign in"}
        </Link>
      </div>
    </div>
  );
}

export function NotFoundPage() {
  return <FullPageMessage code="404" title="Page not found" text="The page you are looking for does not exist." />;
}

export function UnauthorizedPage() {
  return <FullPageMessage code="403" title="Access denied" text="Your role does not have permission to view this page." />;
}
