export function formatPercent(value: number | null | undefined) {
  return value === null || value === undefined ? "—" : `${value.toFixed(1).replace(/\.0$/, "")}%`;
}

export function formatDateTime(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
}

export function initials(name: string) {
  return name
    .split(/\s+/)
    .filter((p) => /^[A-Za-z]/.test(p))
    .slice(-2)
    .map((p) => p[0]!.toUpperCase())
    .join("");
}
