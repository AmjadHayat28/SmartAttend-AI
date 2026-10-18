import { forwardRef, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";
import { cn } from "../../utils/cn";

const controlClass =
  "block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 disabled:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:disabled:bg-slate-800";

interface FieldWrapperProps {
  label: string;
  htmlFor: string;
  error?: string;
  hint?: string;
  children: ReactNode;
}

function FieldWrapper({ label, htmlFor, error, hint, children }: FieldWrapperProps) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-sm font-medium text-slate-700 dark:text-slate-300">
        {label}
      </label>
      {children}
      {error ? (
        <p className="text-xs text-red-600 dark:text-red-400">{error}</p>
      ) : hint ? (
        <p className="text-xs text-slate-500 dark:text-slate-400">{hint}</p>
      ) : null}
    </div>
  );
}

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  name: string;
  error?: string;
  hint?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(({ label, error, hint, className, id, ...rest }, ref) => {
  const fieldId = id ?? rest.name;
  return (
    <FieldWrapper label={label} htmlFor={fieldId} error={error} hint={hint}>
      <input ref={ref} id={fieldId} aria-invalid={!!error} className={cn(controlClass, error && "border-red-400", className)} {...rest} />
    </FieldWrapper>
  );
});
Input.displayName = "Input";

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label: string;
  name: string;
  error?: string;
  placeholder?: string;
  options: { value: string | number; label: string }[];
}

export function Select({ label, error, placeholder, options, className, id, ...rest }: SelectProps) {
  const fieldId = id ?? rest.name;
  return (
    <FieldWrapper label={label} htmlFor={fieldId} error={error}>
      <select id={fieldId} aria-invalid={!!error} className={cn(controlClass, className)} {...rest}>
        {placeholder && <option value="">{placeholder}</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </FieldWrapper>
  );
}

export function Checkbox({ label, checked, onChange, hint, name }: { label: string; checked: boolean; onChange: (v: boolean) => void; hint?: string; name: string }) {
  return (
    <label htmlFor={name} className="flex cursor-pointer items-start gap-2.5">
      <input
        id={name}
        name={name}
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 rounded border-slate-300 text-brand-700 focus:ring-brand-500 dark:border-slate-600"
      />
      <span>
        <span className="block text-sm font-medium text-slate-700 dark:text-slate-300">{label}</span>
        {hint && <span className="block text-xs text-slate-500 dark:text-slate-400">{hint}</span>}
      </span>
    </label>
  );
}
