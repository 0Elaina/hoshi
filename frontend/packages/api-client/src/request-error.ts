type RequestErrorKind =
  "http" | "network" | "timeout" | "invalid-response" | "canceled";

interface RequestErrorOptions {
  kind: RequestErrorKind;
  status?: number;
  code?: string;
  publicMessage?: string;
  cause?: unknown;
}

export class RequestError extends Error {
  readonly kind: RequestErrorKind;
  readonly status?: number;
  readonly code?: string;
  readonly publicMessage?: string;

  constructor({
    kind,
    status,
    code,
    publicMessage,
    cause,
  }: RequestErrorOptions) {
    super(publicMessage ?? kind, { cause });
    this.name = "RequestError";
    this.kind = kind;
    this.status = status;
    this.code = code;
    this.publicMessage = publicMessage;
  }
}
