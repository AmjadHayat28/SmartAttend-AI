import { useCallback, useEffect, useState, type DependencyList } from "react";
import { getErrorMessage } from "../services/api";

/** Run an async loader on mount / when deps change; exposes loading, error and reload. */
export function useAsync<T>(loader: () => Promise<T>, deps: DependencyList = []) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(loader, deps);

  const reload = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    run()
      .then((result) => !cancelled && setData(result))
      .catch((err) => !cancelled && setError(getErrorMessage(err)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [run]);

  useEffect(() => reload(), [reload]);

  return { data, loading, error, reload, setData };
}
