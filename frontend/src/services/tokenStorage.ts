/**
 * Token handling.
 * - Access token: kept in memory only (never in localStorage/sessionStorage). After a reload it is
 *   re-issued from the refresh cookie.
 * - Refresh token: an HttpOnly cookie set by the API. JavaScript can neither read nor send it
 *   anywhere else; the browser attaches it only to /api/v1/auth requests from this site.
 * Older versions kept the refresh token in localStorage: `takeLegacyRefresh` hands it over once so
 * the API can move that session onto the cookie, and deletes it.
 */
const LEGACY_ACCESS_KEY = "sc_access";
const LEGACY_REFRESH_KEY = "sc_refresh";

let accessToken: string | null = null;

function safe<T>(fn: () => T, fallback: T): T {
  try {
    return fn();
  } catch {
    return fallback;
  }
}

export const tokenStorage = {
  getAccess: () => accessToken,
  setAccess(token: string) {
    accessToken = token;
  },
  takeLegacyRefresh(): string | null {
    return safe(() => {
      const legacy = localStorage.getItem(LEGACY_REFRESH_KEY);
      localStorage.removeItem(LEGACY_REFRESH_KEY);
      sessionStorage.removeItem(LEGACY_ACCESS_KEY);
      return legacy;
    }, null);
  },
  clear() {
    accessToken = null;
    safe(() => {
      localStorage.removeItem(LEGACY_REFRESH_KEY);
      sessionStorage.removeItem(LEGACY_ACCESS_KEY);
    }, undefined);
  },
};
