export type ViewKey =
  | "home"
  | "timeline"
  | "catalog"
  | "lists"
  | "insights"
  | "operations"
  | "settings";

export type RouteMap = Record<ViewKey, string>;

type Bootstrap = {
  csrfToken: string;
  routes: RouteMap;
};

const defaultRoutes: RouteMap = {
  home: "/home",
  timeline: "/timeline",
  catalog: "/catalog",
  lists: "/lists",
  insights: "/insights",
  operations: "/data-operations",
  settings: "/settings",
};

function readBootstrap(): Bootstrap {
  const node = document.getElementById("dancing-log-bootstrap");
  if (!node?.textContent) {
    return { csrfToken: "", routes: defaultRoutes };
  }
  try {
    const parsed = JSON.parse(node.textContent) as Partial<Bootstrap>;
    return {
      csrfToken: typeof parsed.csrfToken === "string" ? parsed.csrfToken : "",
      routes: { ...defaultRoutes, ...(parsed.routes ?? {}) },
    };
  } catch {
    return { csrfToken: "", routes: defaultRoutes };
  }
}

export const bootstrap = readBootstrap();

export class ApiError extends Error {
  readonly data: Record<string, unknown>;

  constructor(message: string, data: Record<string, unknown>) {
    super(message);
    this.name = "ApiError";
    this.data = data;
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const init: RequestInit = { ...options, headers };
  if (init.body && typeof init.body !== "string") {
    headers.set("Content-Type", "application/json");
    init.body = JSON.stringify(init.body);
  }
  if ((init.method ?? "GET").toUpperCase() !== "GET") {
    headers.set("X-Dancing-Log-CSRF", bootstrap.csrfToken);
  }

  const response = await fetch(path, init);
  const data = (await response.json()) as Record<string, unknown>;
  if (!response.ok) {
    throw new ApiError(String(data.error ?? "request failed"), data);
  }
  return data as T;
}

export function postJson<T>(path: string, body: Record<string, unknown>): Promise<T> {
  return api<T>(path, { method: "POST", body: body as unknown as BodyInit });
}

export function viewFromPath(pathname: string): ViewKey {
  const entry = Object.entries(bootstrap.routes).find(([, path]) => path === pathname);
  return (entry?.[0] as ViewKey | undefined) ?? "home";
}
