import { useCallback, useEffect, useRef, useState } from "react";
import { getErrorMessage } from "../services/api";
import type { ListParams, Page } from "../types/api";

type Filters = Record<string, string>;

/**
 * Server-side paginated list with debounced search and filters.
 * Changing the search or any filter resets to page 1.
 */
export function usePagedList<T>(
  fetcher: (params: ListParams) => Promise<Page<T>>,
  { pageSize = 20, initialFilters = {} as Filters } = {},
) {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [filters, setFilters] = useState<Filters>(initialFilters);
  const [data, setData] = useState<Page<T> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    const t = window.setTimeout(() => {
      setDebounced(search.trim());
      setPage(1);
    }, 300);
    return () => window.clearTimeout(t);
  }, [search]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetcherRef
      .current({ page, page_size: pageSize, q: debounced || undefined, ...filters })
      .then((result) => {
        if (cancelled) return;
        // Step back if the current page emptied (e.g. after deactivating the last row).
        if (result.items.length === 0 && result.total > 0 && page > 1) setPage(page - 1);
        else setData(result);
      })
      .catch((err) => !cancelled && setError(getErrorMessage(err)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [page, pageSize, debounced, filters, version]);

  const setFilter = useCallback((key: string, value: string) => {
    setFilters((f) => ({ ...f, [key]: value }));
    setPage(1);
  }, []);

  const reload = useCallback(() => setVersion((v) => v + 1), []);

  return { data, loading, error, page, setPage, pageSize, search, setSearch, filters, setFilter, setFilters, reload };
}
