import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Button } from "../../components/ui/Button";
import { Alert } from "../../components/ui/Feedback";
import { Input } from "../../components/ui/FormField";
import { useAuth } from "../../hooks/useAuth";
import { getErrorMessage } from "../../services/api";
import { ROLE_HOME } from "../../types/auth";

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const user = await login({ email: email.trim(), password });
      const from = (location.state as { from?: string } | null)?.from;
      // Only honour the redirect if it belongs to this role's area.
      const home = ROLE_HOME[user.role];
      navigate(from?.startsWith(home) ? from : home, { replace: true });
    } catch (err) {
      setError(getErrorMessage(err, "Login failed"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <h2 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">Sign in</h2>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Use your university email and password.</p>

      <form onSubmit={handleSubmit} className="mt-8 space-y-5" noValidate>
        {error && (
          <Alert>
            {error}
            {error.includes("awaiting approval") && (
              <>
                {" "}
                <Link to="/register/photos" className="font-medium underline">
                  Add or update your registration photos
                </Link>
              </>
            )}
          </Alert>
        )}
        <Input label="Email" name="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@university.edu" />
        <Input label="Password" name="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        <Button type="submit" className="w-full" loading={submitting} disabled={!email || !password}>
          Sign in
        </Button>
      </form>

      <p className="mt-8 text-center text-sm text-slate-500 dark:text-slate-400">
        New student?{" "}
        <Link to="/register" className="font-medium text-brand-700 hover:underline dark:text-brand-200">
          Create your account
        </Link>
      </p>
      <p className="mt-2 text-center text-xs text-slate-400">Teacher and HOD accounts are created by the administration.</p>
    </div>
  );
}
