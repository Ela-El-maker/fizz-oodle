import { ApiError } from "@/shared/lib/errors";
import { shouldRetry, sleep } from "@/shared/lib/retry";

type QueryValue = string | number | boolean | undefined | null;

type RequestOptions = {
  params?: Record<string, QueryValue>;
  method?: string;
  body?: unknown;
};

function buildQuery(params?: Record<string, QueryValue>): string {
  if (!params) return "";
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "");
  if (!entries.length) return "";
  const q = new URLSearchParams(entries.map(([k, v]) => [k, String(v)])).toString();
  return q ? `?${q}` : "";
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const query = buildQuery(options.params);
  const url = `/api${path}${query}`;

  let attempt = 0;
  while (true) {
    const res = await fetch(url, {
      method: options.method || "GET",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
      },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      cache: "no-store",
    });

    if (!res.ok) {
      let payload: unknown = null;
      try {
        payload = await res.json();
      } catch {
        payload = await res.text();
      }
      if (attempt < 2 && shouldRetry(res.status)) {
        attempt += 1;
        await sleep(300 * attempt);
        continue;
      }
      throw new ApiError(`HTTP ${res.status}`, res.status, payload);
    }

    if (res.status === 204) {
      return undefined as T;
    }
    return (await res.json()) as T;
  }
}

export const http = {
  get: <T>(path: string, params?: Record<string, QueryValue>) => request<T>(path, { params }),
  post: <T>(path: string, body?: unknown, params?: Record<string, QueryValue>) =>
    request<T>(path, { method: "POST", body, params }),
};
