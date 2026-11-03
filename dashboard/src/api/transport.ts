/* The one request boundary: query strings, JSON encoding, and every failure
   turned into a code kept with its status. Every domain module sends through it. */
import type { Schemas } from "./schemas";

// `object`, not a record type: a params interface such as `Filters` has no
// index signature, so a record parameter would need a cast at every call site.
export function qs(params: object, keepEmpty?: ReadonlySet<string>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined) continue;
    if (v === "" && !keepEmpty?.has(k)) continue;
    if (Array.isArray(v)) {
      for (const item of v) sp.append(k, String(item));
    } else {
      sp.append(k, String(v));
    }
  }
  return sp.toString();
}

export type HttpMethod = "GET" | "PUT" | "POST" | "PATCH" | "DELETE";

let writes = 0;

/** Writes settled so far. A kept answer (`keptAnswers.ts`) holds only while
 *  this count has not moved since the read behind it started. */
export function writesSettled(): number {
  return writes;
}

// One request boundary owns JSON encoding and backend error extraction. Keeping
// verb helpers as one-line aliases makes the API table readable without letting
// their behavior drift (each verb keeps the backend's error detail body).
export async function requestJSON<T>(url: string, method: HttpMethod, body?: unknown, signal?: AbortSignal): Promise<T> {
  if (method === "GET") return answer<T>(url, method, body, signal);
  try {
    return await answer<T>(url, method, body, signal);
  } finally {
    // Counted once the write settles: an answer kept before it is forgotten,
    // and a read still running is refused when it finishes (`keepAnswer`).
    writes += 1;
  }
}

async function answer<T>(url: string, method: HttpMethod, body?: unknown, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = method === "GET"
      ? await (signal ? fetch(url, { signal }) : fetch(url))
      : await fetch(url, {
          method,
          ...(body === undefined
            ? {}
            : {
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
              }),
        });
  } catch (caught) {
    // The request never got an answer. The browser's own text ("Failed to
    // fetch", "Load failed") is not ours to show; the code is.
    const aborted = caught instanceof DOMException && caught.name === "AbortError";
    throw new ApiError(String(caught), 0, aborted ? "aborted" : "offline");
  }
  if (!res.ok) throw await httpError(res);
  try {
    return (await res.json()) as T;
  } catch (caught) {
    throw new ApiError(`unreadable response: ${String(caught)}`, res.status, "server");
  }
}

export const getJSON = <T>(url: string, signal?: AbortSignal) => requestJSON<T>(url, "GET", undefined, signal);
export const putJSON = <T>(url: string, body: unknown) => requestJSON<T>(url, "PUT", body);
export const postJSON = <T>(url: string, body: unknown = {}) => requestJSON<T>(url, "POST", body);
export const patchJSON = <T>(url: string, body: unknown = {}) => requestJSON<T>(url, "PATCH", body);
export const deleteJSON = <T>(url: string) => requestJSON<T>(url, "DELETE");
/** A write no kept answer can show, so it forgets none of them: only the
 *  viewed mark, which the Board's list alone reads, and the Board keeps nothing. */
export const postMarkJSON = <T>(url: string) => answer<T>(url, "POST", {});

/** The codes the transport itself assigns, beside the API's own
 *  (`Schemas["ErrorCode"]`, tracker/api/errors.py):
 *  - `offline`: no answer at all (the API is down or the app is not running);
 *  - `aborted`: the caller cancelled it; never shown;
 *  - `server`: an answer that explained nothing (a crash page, a proxy, an
 *    unreadable body);
 *  - `invalid-input`: FastAPI refused the request's shape (a 422 list), a defect;
 *  - `unknown`: an error the API sent as bare English, from before codes. */
export type TransportErrorCode = "offline" | "aborted" | "server" | "invalid-input" | "unknown";
export type ErrorCode = Schemas["ErrorCode"] | TransportErrorCode;
export type ErrorParams = Record<string, string | number | string[]>;

/** An HTTP failure that kept its status and its code. Callers that must tell
 *  "this row is gone" from "the request did not get through" need the code,
 *  not the prose: the compare roster evicts a role on 404 and holds it on
 *  anything else, and evicting on a network blip would delete the user's
 *  selection silently. `message` is English for logs; a screen says the code
 *  through `errorText` (api/errorText.ts), never the message. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: ErrorCode = "unknown",
    readonly params: ErrorParams = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export const isNotFound = (error: unknown): boolean =>
  error instanceof ApiError && error.status === 404;

// Every failure becomes a code: the API's own (`{detail: {code, params,
// message}}`), FastAPI's 422 list, bare English from before codes, or no JSON.
async function httpError(res: Response): Promise<ApiError> {
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    return new ApiError(`${res.status} ${res.statusText}`, res.status, "server");
  }
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail) && "code" in detail) {
    const coded = detail as { code: Schemas["ErrorCode"]; params?: ErrorParams; message?: string };
    const params = Object.fromEntries(Object.entries(coded.params && typeof coded.params === "object" ? coded.params : {}).filter(([, v]) =>
      typeof v === "string" || (typeof v === "number" && Number.isFinite(v)) || (Array.isArray(v) && v.every((x) => typeof x === "string")),
    )) as ErrorParams;
    return new ApiError(typeof coded.message === "string" ? coded.message : String(coded.code), res.status,
      typeof coded.code === "string" ? coded.code : "unknown", params);
  }
  if (Array.isArray(detail)) return new ApiError(JSON.stringify(detail), res.status, "invalid-input");
  if (typeof detail === "string") return new ApiError(detail, res.status, res.status >= 500 ? "server" : "unknown");
  return new ApiError(`${res.status} ${res.statusText}`, res.status, "server");
}
