/**
 * Typed client for the Datrix FastAPI backend (PLAN.md §8 + INTERFACES.md "api/").
 */
import type {
  AnalysisPlan,
  ColumnMapping,
  DashboardPayload,
  DataMode,
  DataSpec,
  Dataset,
  Pipeline,
  PipelineCode,
  Plan,
  Project,
  ProjectCreate,
  RerunMode,
  Results,
  Run,
  RunWithKpis,
  Usage,
  Validation,
} from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");

/** Client-side upload limit (mirrors backend settings.max_upload_mb). */
export const MAX_UPLOAD_MB = 200;
export const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;
export const ACCEPTED_EXTENSIONS = [".csv", ".xlsx", ".xls", ".parquet", ".json"];

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function detailToMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI 422: [{loc, msg, type}]
    return detail
      .map((d) => {
        if (d && typeof d === "object" && "msg" in d) {
          const loc = Array.isArray((d as { loc?: unknown[] }).loc)
            ? (d as { loc: unknown[] }).loc.filter((p) => p !== "body").join(".")
            : "";
          return loc ? `${loc}: ${(d as { msg: string }).msg}` : (d as { msg: string }).msg;
        }
        return String(d);
      })
      .join("; ");
  }
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return fallback;
}

export function errorMessage(err: unknown): string {
  // The backend's `detail`, e.g. 402 "OpenAI budget cap reached: …" or 409 "Project 3 is busy …".
  if (err instanceof ApiError) return err.message;
  if (err instanceof TypeError) return `Cannot reach the backend at ${API_URL}. Is it running?`;
  if (err instanceof Error) return err.message;
  return String(err);
}

async function parseError(res: Response): Promise<ApiError> {
  let detail: unknown = undefined;
  try {
    const body = await res.json();
    detail = body?.detail ?? body;
  } catch {
    /* not JSON */
  }
  return new ApiError(res.status, detailToMessage(detail, `${res.status} ${res.statusText}`), detail);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  headers.set("Accept", "application/json");
  const res = await fetch(`${API_URL}${path}`, { ...init, headers, cache: "no-store" });
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : null) as T;
}

const json = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body ?? {}) });

/** Multipart upload with progress (XHR, since fetch has no upload progress). */
function uploadMultipart<T>(path: string, form: FormData, onProgress?: (fraction: number) => void): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_URL}${path}`);
    xhr.setRequestHeader("Accept", "application/json");
    if (onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(e.loaded / e.total);
      };
    }
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch {
        /* ignore */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as T);
      else {
        const detail = (body as { detail?: unknown } | null)?.detail ?? body;
        reject(new ApiError(xhr.status, detailToMessage(detail, `${xhr.status} ${xhr.statusText}`), detail));
      }
    };
    xhr.onerror = () => reject(new TypeError("Network error"));
    xhr.send(form);
  });
}

export const api = {
  /* ---------------- projects ---------------- */
  listProjects: () => request<Project[]>("/projects"),
  getProject: (id: number) => request<Project>(`/projects/${id}`),
  createProject: (body: ProjectCreate) => request<Project>("/projects", json(body)),
  postMessage: (id: number, content: string) => request<Project>(`/projects/${id}/messages`, json({ content })),

  /* ---------------- data spec ---------------- */
  getDataSpec: (id: number) => request<DataSpec>(`/projects/${id}/data-spec`),
  templateCsvUrl: (id: number) => `${API_URL}/projects/${id}/data-spec/template.csv`,

  /* ---------------- datasets ---------------- */
  uploadDatasets: (id: number, files: File[], onProgress?: (f: number) => void) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f, f.name));
    return uploadMultipart<Dataset[]>(`/projects/${id}/datasets`, form, onProgress);
  },
  listDatasets: (id: number) => request<Dataset[]>(`/projects/${id}/datasets`),
  deleteDataset: (id: number, datasetId: number) =>
    request<{ ok: boolean }>(`/projects/${id}/datasets/${datasetId}`, { method: "DELETE" }),

  /* ---------------- validation ---------------- */
  validate: (id: number) => request<Validation>(`/projects/${id}/validate`, { method: "POST" }),
  getValidation: (id: number) => request<Validation | null>(`/projects/${id}/validation`),
  putColumnMapping: (id: number, mapping: ColumnMapping[]) =>
    request<Validation>(`/projects/${id}/column-mapping`, { method: "PUT", body: JSON.stringify({ mapping }) }),

  /* ---------------- plan ---------------- */
  generatePlan: (id: number) => request<Plan>(`/projects/${id}/plan`, { method: "POST" }),
  getPlan: (id: number) => request<Plan | null>(`/projects/${id}/plan`),
  approvePlan: (id: number, plan?: AnalysisPlan) =>
    request<Run>(`/projects/${id}/plan/approve`, json(plan ? { plan } : {})),

  /* ---------------- runs ---------------- */
  listProjectRuns: (id: number) => request<Run[]>(`/projects/${id}/runs`),
  getRun: (runId: number) => request<Run>(`/runs/${runId}`),
  getResults: (runId: number) => request<Results>(`/runs/${runId}/results`),
  getDashboard: (runId: number) => request<DashboardPayload>(`/runs/${runId}/dashboard`),
  thumbnailUrl: (runId: number) => `${API_URL}/runs/${runId}/thumbnail`,
  logsStreamUrl: (runId: number) => `${API_URL}/runs/${runId}/logs/stream`,

  /* ---------------- pipelines ---------------- */
  listPipelines: () => request<Pipeline[]>("/pipelines"),
  getPipeline: (pid: number) => request<Pipeline>(`/pipelines/${pid}`),
  getPipelineCode: (pid: number) => request<PipelineCode>(`/pipelines/${pid}/code`),
  listPipelineRuns: (pid: number) => request<RunWithKpis[]>(`/pipelines/${pid}/runs`),
  createPipelineRun: (
    pid: number,
    opts: {
      files: File[];
      mode: RerunMode;
      data_mode: DataMode;
      mapping_override?: Record<string, string>;
    },
    onProgress?: (f: number) => void,
  ) => {
    const form = new FormData();
    opts.files.forEach((f) => form.append("files", f, f.name));
    form.append("mode", opts.mode);
    form.append("data_mode", opts.data_mode);
    form.append("mapping_override", JSON.stringify(opts.mapping_override ?? {}));
    return uploadMultipart<Run>(`/pipelines/${pid}/runs`, form, onProgress);
  },
  retryPipelineRun: (
    pid: number,
    runId: number,
    body: { mapping_override?: Record<string, string>; data_mode?: DataMode },
  ) => request<Run>(`/pipelines/${pid}/runs/${runId}/retry`, json(body)),
  automap: (pid: number, datasetIds: number[]) =>
    request<Record<string, string>>(`/pipelines/${pid}/automap`, json({ dataset_ids: datasetIds })),
  forkPipeline: (pid: number) => request<{ project_id: number }>(`/pipelines/${pid}/fork`, { method: "POST" }),

  /* ---------------- usage ---------------- */
  getUsage: () => request<Usage>("/usage"),
};

/**
 * Live run logs over SSE (`GET /runs/{id}/logs/stream`): events named `log` (data = one line)
 * and a final `done`. Returns a function that closes the stream.
 */
export function streamLogs(
  runId: number,
  onLine: (line: string) => void,
  onDone: (error?: Event) => void,
): () => void {
  const es = new EventSource(api.logsStreamUrl(runId));
  let closed = false;
  const close = () => {
    if (!closed) {
      closed = true;
      es.close();
    }
  };
  es.addEventListener("log", (e) => onLine((e as MessageEvent<string>).data));
  // Fallback for un-named events.
  es.onmessage = (e) => onLine(e.data);
  es.addEventListener("done", () => {
    close();
    onDone();
  });
  es.onerror = (e) => {
    // EventSource would auto-reconnect and replay; we close and let the caller decide.
    if (closed) return;
    close();
    onDone(e);
  };
  return close;
}
