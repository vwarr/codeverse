// A random ID for this browser, kept in localStorage. The History page lists only the reports
// started with this ID (there are no accounts). Treat it like a password: it is never shown.

const KEY = 'cv_client_id';

export function clientId(): string {
  try {
    const saved = window.localStorage.getItem(KEY);
    if (saved) {
      return saved;
    }
    const id = crypto.randomUUID();
    window.localStorage.setItem(KEY, id);
    return id;
  } catch {
    // Storage blocked: history will not work, but an interview still can.
    return '';
  }
}
