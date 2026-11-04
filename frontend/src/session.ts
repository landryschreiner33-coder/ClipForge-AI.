/**
 * Who is signed in, and the request protection cloud mode needs. Desktop mode has no sign-in: /api/auth/me says
 * "local" and nothing here changes a request. In cloud mode every change (POST/PUT/PATCH/DELETE) carries the
 * session's CSRF token, and an ended session shows the sign-in page instead of failing silently.
 */
export type Me = { mode: "local" | "cloud"; signed_in: boolean; name?: string; workspace_id?: string; primary?: boolean; csrf?: string };

let csrf = "";
let installed = false;
const MUTATING = new Set(["POST", "PUT", "PATCH", "DELETE"]);
export const SIGNED_OUT = "clipforge:signed-out";

function sameOrigin(url: string): boolean {
  try {
    return new URL(url, window.location.href).origin === window.location.origin;
  } catch {
    return false;
  }
}

/** Add the CSRF header to every same-origin change made with fetch or XMLHttpRequest (all of the app's calls). */
export function installRequestProtection() {
  if (installed) return;
  installed = true;
  const realFetch = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const method = (init?.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
    if (csrf && MUTATING.has(method) && sameOrigin(url)) {
      const headers = new Headers(init?.headers || (input instanceof Request ? input.headers : undefined));
      headers.set("X-ClipForge-CSRF", csrf);
      init = { ...init, headers };
    }
    const res = await realFetch(input, init);
    if (res.status === 401 && sameOrigin(url) && !url.includes("/api/auth/me")) {
      window.dispatchEvent(new Event(SIGNED_OUT));
    }
    return res;
  };
  const open = XMLHttpRequest.prototype.open;
  const send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (this: XMLHttpRequest & { _cfMethod?: string; _cfUrl?: string }, method: string, url: string | URL, ...rest: unknown[]) {
    this._cfMethod = method.toUpperCase();
    this._cfUrl = String(url);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return (open as any).call(this, method, url, ...rest);
  } as typeof XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.send = function (this: XMLHttpRequest & { _cfMethod?: string; _cfUrl?: string }, body?: Document | XMLHttpRequestBodyInit | null) {
    if (csrf && this._cfMethod && MUTATING.has(this._cfMethod) && sameOrigin(this._cfUrl || "")) {
      this.setRequestHeader("X-ClipForge-CSRF", csrf);
    }
    return send.call(this, body);
  };
}

export async function loadMe(): Promise<Me> {
  try {
    const res = await fetch("/api/auth/me");
    const me = (await res.json()) as Me;
    csrf = me.csrf || "";
    return me;
  } catch {
    return { mode: "local", signed_in: true };
  }
}

export function signInUrl(): string {
  const back = window.location.hash || "#/";
  return `/api/auth/login?next=${encodeURIComponent(back)}`;
}

export async function signOut(everywhere = false): Promise<void> {
  await fetch(everywhere ? "/api/auth/logout-all" : "/api/auth/logout", { method: "POST" });
  csrf = "";
  window.location.hash = "#/";
  window.location.reload();
}
