import axios from "axios";
import { CheckCircle2, LogOut } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { FaceEnrollmentPanel } from "../../components/face/FaceEnrollmentPanel";
import { Logo } from "../../components/layout/Logo";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { Alert } from "../../components/ui/Feedback";
import { Input } from "../../components/ui/FormField";
import { getErrorMessage } from "../../services/api";
import { createEnrollmentClient, createOnboardingHttp, onboardingToken, requestOnboardingToken } from "../../services/faceEnrollmentService";
import { cn } from "../../utils/cn";

const STEPS = ["Account created", "Profile photo", "Face photos", "Submit for review", "Approval"];

/**
 * Registration step 2: a newly registered (pending) student adds their photos using the
 * short-lived onboarding token. Returning students re-enter their email and password.
 */
export function OnboardingPage() {
  const [token, setToken] = useState<string | null>(() => onboardingToken.get());
  const [submitted, setSubmitted] = useState(false);
  const client = useMemo(() => {
    if (!token) return null;
    const http = createOnboardingHttp(token);
    http.interceptors.response.use(undefined, (err) => {
      // Expired or revoked onboarding token: ask the student to sign in to this step again.
      if (axios.isAxiosError(err) && err.response?.status === 401) {
        onboardingToken.clear();
        setToken(null);
      }
      return Promise.reject(err);
    });
    return createEnrollmentClient(http);
  }, [token]);

  function leave() {
    onboardingToken.clear();
    setToken(null);
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4">
          <Logo />
          {token && (
            <Button variant="ghost" size="sm" onClick={leave}>
              <LogOut className="h-4 w-4" /> Finish later
            </Button>
          )}
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">Complete your registration</h1>
        <ol className="mt-4 flex flex-wrap gap-2 text-xs sm:text-sm" aria-label="Registration progress">
          {STEPS.map((step, i) => {
            const done = i === 0 || (submitted && i < 4);
            const current = !done && (i === (submitted ? 4 : 1));
            return (
              <li key={step} className={cn("flex items-center gap-1.5 rounded-full px-3 py-1", done ? "bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300" : current ? "bg-brand-50 text-brand-800 dark:bg-brand-900/40 dark:text-brand-100" : "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400")}>
                {done && <CheckCircle2 className="h-3.5 w-3.5" />}
                {i + 1}. {step}
              </li>
            );
          })}
        </ol>
        <div className="mt-6">
          {client ? (
            <>
              <FaceEnrollmentPanel client={client} onSubmitted={() => setSubmitted(true)} />
              <p className="mt-6 text-center text-sm text-slate-500">
                Your account is <strong>pending approval</strong>. You can sign in once your department approves it.{" "}
                <Link to="/login" className="font-medium text-brand-700 hover:underline dark:text-brand-200" onClick={() => onboardingToken.clear()}>
                  Back to sign in
                </Link>
              </p>
            </>
          ) : (
            <ResumeForm onToken={(t) => { onboardingToken.set(t); setToken(t); }} />
          )}
        </div>
      </main>
    </div>
  );
}

function ResumeForm({ onToken }: { onToken: (token: string) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      onToken(await requestOnboardingToken(email.trim(), password));
    } catch (err) {
      setError(getErrorMessage(err, "Could not continue"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className="mx-auto max-w-md p-6">
      <h2 className="font-semibold text-slate-900 dark:text-white">Continue adding your photos</h2>
      <p className="mt-1 text-sm text-slate-500">For registrations still waiting for approval. Approved students should sign in normally.</p>
      <form onSubmit={submit} className="mt-5 space-y-4" noValidate>
        {error && <Alert>{error}</Alert>}
        <Input label="Email" name="ob-email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
        <Input label="Password" name="ob-password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        <Button type="submit" className="w-full" loading={loading} disabled={!email || !password}>
          Continue
        </Button>
      </form>
      <p className="mt-4 text-center text-sm">
        <Link to="/login" className="text-brand-700 hover:underline dark:text-brand-200">
          Back to sign in
        </Link>
      </p>
    </Card>
  );
}
