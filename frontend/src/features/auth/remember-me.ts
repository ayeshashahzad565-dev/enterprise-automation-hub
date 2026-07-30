/**
 * "Remember me" support.
 *
 * `@supabase/ssr`'s browser client hard-codes its session cookie to a
 * 400-day `maxAge` — its cookie storage adapter forces
 * `maxAge: DEFAULT_COOKIE_OPTIONS.maxAge` on every write regardless of any
 * `cookieOptions.maxAge` passed to `createBrowserClient` (see
 * `@supabase/ssr/dist/main/cookies.js`), so there is no supported way to
 * make the underlying cookie itself shorter-lived. Sessions are therefore
 * already persistent by default.
 *
 * "Remember me" is implemented as an independent local preference instead:
 * `SESSION_ALIVE_KEY` lives in `sessionStorage`, which the browser clears
 * when the browser (or tab) actually closes, but keeps across a same-tab
 * refresh or client-side navigation. Combined with the persisted
 * `REMEMBER_ME_KEY` preference, `useAuthSession` can tell "the user is still
 * in the browser session they logged in during" apart from "the browser was
 * closed and reopened" and end the session in only the latter case when the
 * user opted out of being remembered.
 */

const REMEMBER_ME_KEY = "eah:remember-me";
const SESSION_ALIVE_KEY = "eah:session-alive";

export function setRememberMePreference(remember: boolean) {
  localStorage.setItem(REMEMBER_ME_KEY, remember ? "1" : "0");
}

function isRemembered(): boolean {
  return localStorage.getItem(REMEMBER_ME_KEY) !== "0";
}

/** Marks the current browser session alive, returning whether it already was. */
function markSessionAlive(): boolean {
  const wasAlive = sessionStorage.getItem(SESSION_ALIVE_KEY) === "1";
  sessionStorage.setItem(SESSION_ALIVE_KEY, "1");
  return wasAlive;
}

/** True if this is a fresh browser session (reopened after closing) and the user opted out of being remembered. */
export function shouldEndUnrememberedSession(): boolean {
  const wasAlive = markSessionAlive();
  return !isRemembered() && !wasAlive;
}
