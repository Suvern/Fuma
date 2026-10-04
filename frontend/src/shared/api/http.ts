import { api } from "./client";
import type { components, paths } from "../../generated/api";
export type DTO<K extends keyof components["schemas"]> =
  components["schemas"][K];
type Method = "get" | "post" | "put" | "patch" | "delete";
type Operation<P extends keyof paths, M extends Method> = NonNullable<
  paths[P][M]
>;
type Content<T> = T extends { content: { "application/json": infer V } }
  ? V
  : never;
type Success<T> = T extends { responses: infer R }
  ? Content<R[Extract<keyof R, 200 | 201 | 202>]>
  : never;
type Body<T> = T extends {
  requestBody: { content: { "application/json": infer V } };
}
  ? V
  : undefined;
export type WriteOptions = {
  id?: string;
  platform?: string;
  revision?: number;
  key?: string;
};
export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: DTO<"ErrorDetail">,
    public requestId?: string,
  ) {
    super(detail.message);
  }
}
export async function read<P extends keyof paths>(
  path: P,
  options: {
    id?: string;
    platform?: string;
    query?: Record<string, unknown>;
    signal?: AbortSignal;
  } = {},
): Promise<Success<Operation<P, "get">>> {
  return request(path, "get", undefined as never, options);
}
export async function write<
  P extends keyof paths,
  M extends Exclude<Method, "get">,
>(
  path: P,
  method: M,
  body: Body<Operation<P, M>>,
  options: WriteOptions = {},
): Promise<Success<Operation<P, M>>> {
  const context = await read("/api/v1/auth/browser-context");
  return request(path, method, body, { ...options, csrf: context.csrf_token });
}
async function request<P extends keyof paths, M extends Method>(
  path: P,
  method: M,
  body: Body<Operation<P, M>>,
  options: WriteOptions & {
    csrf?: string;
    query?: Record<string, unknown>;
    signal?: AbortSignal;
  },
): Promise<Success<Operation<P, M>>> {
  const headers: Record<string, string> = {};
  if (options.csrf) headers["X-CSRF-Token"] = options.csrf;
  if (options.revision !== undefined)
    headers["If-Match"] = `"${options.revision}"`;
  if (options.key) headers["Idempotency-Key"] = options.key;
  const timeout = AbortSignal.timeout(30_000);
  const result = await api.request(
    method,
    path as never,
    {
      params: {
        path: {
          ...(options.id ? { id: options.id } : {}),
          ...(options.platform ? { platform: options.platform } : {}),
        },
        query: options.query,
        header: headers,
      },
      body,
      signal: options.signal
        ? AbortSignal.any([options.signal, timeout])
        : timeout,
    } as never,
  );
  if (!result.response.ok) {
    const error = result.error as DTO<"ErrorResponse"> | undefined;
    throw new ApiError(
      result.response.status,
      error?.error ?? {
        code: "HTTP_ERROR",
        retryable: false,
        message: "请求未完成，请刷新状态后重试。",
      },
      error?.request_id,
    );
  }
  return result.data as Success<Operation<P, M>>;
}
export function safeReturnPath(value: string | null): string {
  return value?.startsWith("/") &&
    !value.startsWith("//") &&
    !value.includes("\\") &&
    ![...value].some(
      (char) => char.charCodeAt(0) <= 32 || char.charCodeAt(0) === 127,
    )
    ? value
    : "/";
}
export function ssoUrl(
  returnTo = window.location.pathname + window.location.search,
) {
  return `/api/v1/auth/feishu/start?return_to=${encodeURIComponent(safeReturnPath(returnTo))}`;
}
