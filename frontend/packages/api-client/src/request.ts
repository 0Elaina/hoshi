import axios, {
  AxiosError,
  type AxiosRequestConfig,
  type AxiosResponse,
  type Method,
} from "axios";
import { z, type ZodType } from "zod";
import { RequestError } from "./request-error";

const successCode = "SUCCESS";

const responseSchema = z.object({
  data: z.unknown().refine((value) => value !== undefined),
  code: z.string().min(1),
  message: z.string(),
});

interface RequestOptions {
  baseURL: string;
  timeout?: number;
}

export interface RequestConfig<T = unknown> {
  method: Uppercase<Method>;
  url: string;
  params?: object;
  data?: unknown;
  headers?: AxiosRequestConfig<unknown>["headers"];
  signal?: AbortSignal;
  schema?: ZodType<T>;
}

export function createRequest({ baseURL, timeout = 10_000 }: RequestOptions) {
  const client = axios.create({
    baseURL,
    timeout,
    allowAbsoluteUrls: false,
    headers: { Accept: "application/json" },
  });

  return async function request<T = unknown>({
    method,
    url,
    params,
    data,
    headers,
    signal,
    schema,
  }: RequestConfig<T>): Promise<T> {
    const response = await client
      .request<
        unknown,
        AxiosResponse<unknown, unknown, object>,
        unknown,
        object
      >({
        method,
        url,
        params,
        data,
        headers,
        signal,
      })
      .catch((error: unknown) => {
        throw normalizeRequestError(error);
      });

    const parsed = responseSchema.safeParse(response.data);
    if (!parsed.success) {
      throw new RequestError({
        kind: "invalid-response",
        status: response.status,
        cause: parsed.error,
      });
    }
    if (parsed.data.code !== successCode) {
      throw new RequestError({
        kind: "invalid-response",
        status: response.status,
        code: parsed.data.code,
      });
    }
    if (schema === undefined) {
      return parsed.data.data as T;
    }

    const payload = await schema.safeParseAsync(parsed.data.data);
    if (!payload.success) {
      throw new RequestError({
        kind: "invalid-response",
        status: response.status,
        cause: payload.error,
      });
    }
    return payload.data;
  };
}

function normalizeRequestError(error: unknown): Error {
  if (axios.isCancel(error)) {
    return new RequestError({ kind: "canceled", cause: error });
  }
  if (!axios.isAxiosError<unknown, unknown, unknown>(error)) {
    return error instanceof Error
      ? error
      : new Error("Unexpected request error", { cause: error });
  }

  if (error.response !== undefined) {
    const { data, status } = error.response;
    const parsed = responseSchema.safeParse(data);
    const details =
      parsed.success &&
      parsed.data.data === null &&
      parsed.data.code !== successCode
        ? parsed.data
        : undefined;

    return new RequestError({
      kind: "http",
      status,
      code: details?.code,
      publicMessage: details?.message,
      cause: error,
    });
  }
  if (
    error.code === AxiosError.ECONNABORTED ||
    error.code === AxiosError.ETIMEDOUT
  ) {
    return new RequestError({ kind: "timeout", cause: error });
  }
  if (error.code === AxiosError.ERR_NETWORK) {
    return new RequestError({ kind: "network", cause: error });
  }
  return error;
}
