import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { he } from "../i18n/he";

/** Hebrew message for a failed request (network problems are told apart from server errors). */
export function errorMessage(e: unknown): string {
  return e instanceof ApiError && e.status === 0 ? he.common.networkError : he.common.genericError;
}

export interface Loaded<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
  setData: (next: T | null) => void;
}

/**
 * Run `fetcher` on mount and whenever `deps` change. Only the most recent request may update the
 * state (an older, slower response is discarded). Existing data stays available while reloading.
 */
export function useAsync<T>(fetcher: () => Promise<T>, deps: unknown[]): Loaded<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const latest = useRef(0);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const reload = useCallback(() => {
    const ticket = ++latest.current;
    setLoading(true);
    setError(null);
    fetcher()
      .then((value) => {
        if (ticket !== latest.current) return;
        setData(value);
        setLoading(false);
      })
      .catch((e) => {
        if (ticket !== latest.current) return;
        setError(errorMessage(e));
        setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(reload, [reload]);
  return { data, error, loading, reload, setData };
}
