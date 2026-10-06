import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { he } from "../i18n/he";

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError && e.status === 0) return he.common.networkError;
  return he.common.genericError;
}

/** Load data on mount / when deps change. Ignores results of stale requests. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(() => {
    const id = ++seq.current;
    setLoading(true);
    setError(null);
    fn().then(
      (d) => { if (id === seq.current) { setData(d); setLoading(false); } },
      (e) => { if (id === seq.current) { setError(errorMessage(e)); setLoading(false); } },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => { run(); }, [run]);
  return { data, error, loading, reload: run, setData };
}
