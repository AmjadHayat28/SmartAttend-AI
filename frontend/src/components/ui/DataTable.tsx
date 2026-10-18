import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import type { Page } from "../../types/api";
import { cn } from "../../utils/cn";
import { EmptyState, ErrorState, Spinner } from "./Feedback";
import { Pagination } from "./Pagination";

export interface Column<T> {
  header: string;
  cell: (row: T) => ReactNode;
  className?: string;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: Page<T> | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onPageChange: (page: number) => void;
  rowKey: (row: T) => string | number;
  empty: { title: string; description?: string; icon?: LucideIcon; action?: ReactNode };
  rowClassName?: (row: T) => string | undefined;
}

export function DataTable<T>({ columns, data, loading, error, onRetry, onPageChange, rowKey, empty, rowClassName }: DataTableProps<T>) {
  if (error) return <ErrorState message={error} onRetry={onRetry} />;
  if (!data) return <Spinner />;
  if (!data.items.length && !loading) return <EmptyState {...empty} />;

  return (
    <div className={cn("relative", loading && "opacity-60 transition-opacity")} aria-busy={loading}>
      <div className="relative overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
          <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 dark:bg-slate-900/60 dark:text-slate-400">
            <tr>
              {columns.map((c) => (
                <th key={c.header} scope="col" className={cn("whitespace-nowrap px-5 py-3", c.className)}>
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
            {data.items.map((row) => (
              <tr key={rowKey(row)} className={cn("hover:bg-slate-50 dark:hover:bg-slate-800/40", rowClassName?.(row))}>
                {columns.map((c) => (
                  <td key={c.header} className={cn("px-5 py-3 align-middle", c.className)}>
                    {c.cell(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={onPageChange} />
    </div>
  );
}
