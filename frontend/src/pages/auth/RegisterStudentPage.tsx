import { CheckCircle2 } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "../../components/ui/Button";
import { Alert, Spinner } from "../../components/ui/Feedback";
import { Input, Select } from "../../components/ui/FormField";
import { useAsync } from "../../hooks/useAsync";
import { getErrorMessage } from "../../services/api";
import { authService } from "../../services/authService";
import { onboardingToken } from "../../services/faceEnrollmentService";

const EMPTY = {
  full_name: "",
  registration_no: "",
  email: "",
  password: "",
  confirm: "",
  department_id: "",
  batch_id: "",
  semester_id: "",
  section_id: "",
};
type FormState = typeof EMPTY;

function validate(f: FormState): Partial<Record<keyof FormState, string>> {
  const errors: Partial<Record<keyof FormState, string>> = {};
  if (f.full_name.trim().length < 2) errors.full_name = "Enter your full name";
  if (!/^[A-Za-z0-9\-/]{3,50}$/.test(f.registration_no.trim())) errors.registration_no = "Letters, digits, '-' or '/' only";
  if (!/^\S+@\S+\.\S+$/.test(f.email)) errors.email = "Enter a valid email";
  if (f.password.length < 8 || !/[a-z]/.test(f.password) || !/[A-Z]/.test(f.password) || !/\d/.test(f.password))
    errors.password = "At least 8 characters with upper-case, lower-case and a digit";
  if (f.confirm !== f.password) errors.confirm = "Passwords do not match";
  for (const key of ["department_id", "batch_id", "semester_id", "section_id"] as const) {
    if (!f[key]) errors[key] = "Required";
  }
  return errors;
}

export function RegisterStudentPage() {
  const structure = useAsync(() => authService.academicStructure());
  const [form, setForm] = useState<FormState>(EMPTY);
  const [touched, setTouched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const navigate = useNavigate();

  const errors = touched ? validate(form) : {};

  // Cascading dropdowns: department → batch → semester → section
  const department = useMemo(() => structure.data?.find((d) => String(d.id) === form.department_id), [structure.data, form.department_id]);
  const batch = department?.batches.find((b) => String(b.id) === form.batch_id);
  const semester = batch?.semesters.find((s) => String(s.id) === form.semester_id);

  function update(field: keyof FormState, value: string) {
    setForm((f) => {
      const next = { ...f, [field]: value };
      // Reset dependent selections when a parent changes.
      if (field === "department_id") Object.assign(next, { batch_id: "", semester_id: "", section_id: "" });
      if (field === "batch_id") Object.assign(next, { semester_id: "", section_id: "" });
      if (field === "semester_id") next.section_id = "";
      return next;
    });
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (Object.keys(validate(form)).length) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await authService.registerStudent({
        full_name: form.full_name,
        registration_no: form.registration_no,
        email: form.email.trim(),
        password: form.password,
        department_id: Number(form.department_id),
        batch_id: Number(form.batch_id),
        semester_id: Number(form.semester_id),
        section_id: Number(form.section_id),
      });
      onboardingToken.set(res.onboarding_token);
      setDone(res.message);
      navigate("/register/photos");
    } catch (err) {
      setError(getErrorMessage(err, "Registration failed"));
    } finally {
      setSubmitting(false);
    }
  }

  if (done) {
    return (
      <div className="text-center">
        <CheckCircle2 className="mx-auto h-12 w-12 text-emerald-600" />
        <h2 className="mt-4 text-xl font-semibold text-slate-900 dark:text-white">Registration submitted</h2>
        <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">{done}</p>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Status: <strong>Pending Approval</strong></p>
        <Link to="/login" className="mt-6 inline-block text-sm font-medium text-brand-700 hover:underline dark:text-brand-200">
          Back to sign in
        </Link>
      </div>
    );
  }

  return (
    <div>
      <h2 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">Student registration</h2>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
        Your account will be reviewed by your department before you can sign in.
      </p>

      {structure.loading ? (
        <Spinner label="Loading departments…" />
      ) : structure.error ? (
        <div className="mt-6">
          <Alert>{structure.error}</Alert>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="mt-6 space-y-4" noValidate>
          {error && <Alert>{error}</Alert>}
          <Input label="Full name" name="full_name" value={form.full_name} onChange={(e) => update("full_name", e.target.value)} error={errors.full_name} autoComplete="name" />
          <div className="grid gap-4 sm:grid-cols-2">
            <Input label="Registration no." name="registration_no" value={form.registration_no} onChange={(e) => update("registration_no", e.target.value)} error={errors.registration_no} placeholder="F23CSE01" />
            <Input label="Email" name="email" type="email" value={form.email} onChange={(e) => update("email", e.target.value)} error={errors.email} autoComplete="email" />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Input label="Password" name="password" type="password" value={form.password} onChange={(e) => update("password", e.target.value)} error={errors.password} autoComplete="new-password" />
            <Input label="Confirm password" name="confirm" type="password" value={form.confirm} onChange={(e) => update("confirm", e.target.value)} error={errors.confirm} autoComplete="new-password" />
          </div>
          <Select
            label="Department"
            name="department_id"
            value={form.department_id}
            onChange={(e) => update("department_id", e.target.value)}
            placeholder="Select department"
            options={(structure.data ?? []).map((d) => ({ value: d.id, label: d.label }))}
            error={errors.department_id}
          />
          <div className="grid gap-4 sm:grid-cols-3">
            <Select label="Batch" name="batch_id" value={form.batch_id} onChange={(e) => update("batch_id", e.target.value)} placeholder="Select" disabled={!department} options={(department?.batches ?? []).map((b) => ({ value: b.id, label: b.label }))} error={errors.batch_id} />
            <Select label="Semester" name="semester_id" value={form.semester_id} onChange={(e) => update("semester_id", e.target.value)} placeholder="Select" disabled={!batch} options={(batch?.semesters ?? []).map((s) => ({ value: s.id, label: s.label }))} error={errors.semester_id} />
            <Select label="Section" name="section_id" value={form.section_id} onChange={(e) => update("section_id", e.target.value)} placeholder="Select" disabled={!semester} options={(semester?.sections ?? []).map((s) => ({ value: s.id, label: s.label }))} error={errors.section_id} />
          </div>
          <Alert tone="info">Profile and face photos (front, left, right) are uploaded after this step is enabled in the face-enrollment module.</Alert>
          <Button type="submit" className="w-full" loading={submitting}>
            Submit registration
          </Button>
          <p className="text-center text-sm text-slate-500 dark:text-slate-400">
            Already registered?{" "}
            <Link to="/login" className="font-medium text-brand-700 hover:underline dark:text-brand-200">
              Sign in
            </Link>
          </p>
        </form>
      )}
    </div>
  );
}
