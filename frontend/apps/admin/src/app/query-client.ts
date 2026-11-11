import { RequestError } from "@hoshi/api-client";
import {
  isCancelledError,
  MutationCache,
  QueryCache,
  QueryClient,
} from "@tanstack/react-query";

interface ErrorFeedbackMeta extends Record<string, unknown> {
  errorFeedback?: "local";
}

declare module "@tanstack/react-query" {
  interface Register {
    queryMeta: ErrorFeedbackMeta;
    mutationMeta: ErrorFeedbackMeta;
  }
}

const errorMessages = {
  http: "请求失败，请稍后重试",
  network: "网络连接失败，请检查网络后重试",
  timeout: "请求超时，请稍后重试",
  "invalid-response": "服务响应格式异常，请稍后重试",
};

export function createAdminQueryClient(notifyError: (message: string) => void) {
  function reportError(error: unknown, meta?: ErrorFeedbackMeta) {
    if (meta?.errorFeedback === "local" || isCancelledError(error)) {
      return;
    }
    if (!(error instanceof RequestError)) {
      notifyError(errorMessages.http);
      return;
    }
    if (error.kind !== "canceled") {
      notifyError(error.publicMessage?.trim() || errorMessages[error.kind]);
    }
  }

  return new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (query.state.data === undefined) {
          reportError(error, query.meta);
        }
      },
    }),
    mutationCache: new MutationCache({
      onError: (error, _variables, _onMutateResult, mutation) => {
        reportError(error, mutation.meta);
      },
    }),
    defaultOptions: {
      queries: { retry: shouldRetryQuery },
      mutations: { retry: false },
    },
  });
}

function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (failureCount >= 1 || !(error instanceof RequestError)) {
    return false;
  }
  return (
    error.kind === "network" ||
    error.kind === "timeout" ||
    (error.kind === "http" &&
      error.status !== undefined &&
      error.status >= 500 &&
      error.status < 600)
  );
}
