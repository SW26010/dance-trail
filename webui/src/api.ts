import { z } from "zod";

import { apiErrorResponseSchema } from "./apiContracts";

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

export class ApiContractError extends Error {
  constructor(path: string, cause: unknown) {
    super(`Invalid API response from ${path}`, { cause });
    this.name = "ApiContractError";
  }
}

export async function api<Schema extends z.ZodType>(
  path: string,
  schema: Schema,
  options: RequestInit = {},
): Promise<z.output<Schema>> {
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
  let data: unknown;
  try {
    data = await response.json();
  } catch (error) {
    throw new ApiContractError(path, error);
  }
  if (!response.ok) {
    const errorData = apiErrorResponseSchema.safeParse(data);
    if (!errorData.success) {
      throw new ApiContractError(path, errorData.error);
    }
    const message = typeof errorData.data.error === "string" ? errorData.data.error : "request failed";
    throw new ApiError(message, errorData.data);
  }
  const parsed = schema.safeParse(data);
  if (!parsed.success) {
    throw new ApiContractError(path, parsed.error);
  }
  return parsed.data;
}

export function postJson<Schema extends z.ZodType>(
  path: string,
  schema: Schema,
  body: Record<string, unknown>,
): Promise<z.output<Schema>> {
  return api(path, schema, { method: "POST", body: body as unknown as BodyInit });
}

export function viewFromPath(pathname: string): ViewKey {
  const entry = Object.entries(bootstrap.routes).find(([, path]) => path === pathname);
  return (entry?.[0] as ViewKey | undefined) ?? "home";
}
