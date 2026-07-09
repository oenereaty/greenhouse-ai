export interface JobStatus<T = unknown> {
  id: string;
  status: "queued" | "running" | "done" | "error";
  result: T | null;
  error: string | null;
  elapsed_seconds: number | null;
}
