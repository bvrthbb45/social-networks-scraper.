import { useCallback, useState, type FormEvent } from "react";
import { ApiError } from "../../api/client";
import { he } from "../../i18n/he";
import { errorMessage } from "../../lib/useAsync";

/** Hebrew text for a failed sign-in step. `byStatus` lets a step give its own wording to a status. */
export function signInError(e: unknown, byStatus: Partial<Record<number, string>> = {}): string {
  if (e instanceof ApiError) {
    if (byStatus[e.status]) return byStatus[e.status]!;
    if (e.status === 401) return he.auth.invalidCredentials;
    if (e.status === 429) return he.auth.tooMany;
  }
  return errorMessage(e);
}

/**
 * Shared behaviour of every sign-in form: prevent the native submit, show "busy" while the request
 * runs, and turn a failure into a message. `action` throws to signal failure.
 */
export function useSubmit(action: () => Promise<void>, onError: (e: unknown) => string = signInError) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = useCallback(
    async (event?: FormEvent) => {
      event?.preventDefault();
      setBusy(true);
      setError(null);
      try {
        await action();
      } catch (e) {
        setError(onError(e));
        setBusy(false);
        return;
      }
      setBusy(false);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [action, onError],
  );
  return { busy, error, submit };
}
