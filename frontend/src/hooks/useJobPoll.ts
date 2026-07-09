import { useCallback, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import type { JobStatus } from "../types/jobs";

const TERMINAL = new Set(["done", "error"]);

/**
 * The backend keeps jobs in memory only. After a server restart or TTL eviction a
 * job_id persisted in localStorage is unknown and `/jobs/:id` returns 404 — which
 * must end the poll rather than spin on "실행 중" forever.
 */
function isJobExpired(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

/**
 * Wraps the submit-and-poll job pattern used by every slow-LLM endpoint.
 * `storageKey` persists the in-flight job_id to localStorage so polling
 * resumes automatically after a page refresh.
 */
export function useJobPoll<T = unknown>(storageKey: string) {
  const [jobId, setJobId] = useState<string | null>(() => localStorage.getItem(storageKey));
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    if (jobId) localStorage.setItem(storageKey, jobId);
    else localStorage.removeItem(storageKey);
  }, [jobId, storageKey]);

  const query = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.get<JobStatus<T>>(`/jobs/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (q) => (q.state.data && TERMINAL.has(q.state.data.status) ? false : 2000),
    // Keep polling while the tab is backgrounded — LLM jobs run 30–60s and users
    // routinely switch away while waiting; without this the poll pauses until the
    // tab regains focus, leaving the result stuck on "실행 중".
    refetchIntervalInBackground: true,
    // Never retry a 404 (the job is gone for good); allow a couple of retries for
    // transient network errors.
    retry: (failureCount, error) => !isJobExpired(error) && failureCount < 2,
  });

  // A stored job the backend has forgotten (restart / eviction) 404s forever. Drop
  // the stale id so the card returns to its idle state instead of showing a phantom
  // "실행 중" and polling a dead id indefinitely.
  useEffect(() => {
    if (isJobExpired(query.error)) setJobId(null);
  }, [query.error]);

  // Never rejects — submission failures (rate limit, network error, validation
  // error) are recorded in submitError instead of becoming an unhandled
  // promise rejection that the caller's onClick silently swallows.
  const submit = useCallback(async (fn: () => Promise<{ job_id: string }>) => {
    setSubmitError(null);
    try {
      const { job_id } = await fn();
      setJobId(job_id);
      return job_id;
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : String(e));
      return null;
    }
  }, []);

  const reset = useCallback(() => {
    setJobId(null);
    setSubmitError(null);
  }, []);

  return {
    jobId,
    job: query.data,
    isRunning: !!jobId && (!query.data || query.data.status === "queued" || query.data.status === "running"),
    isDone: query.data?.status === "done",
    isError: query.data?.status === "error",
    submitError,
    submit,
    reset,
  };
}
