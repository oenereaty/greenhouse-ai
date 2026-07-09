import type { ReactNode } from "react";
import { useJobPoll } from "../hooks/useJobPoll";

export function cleanAiText(value: unknown): string {
  return String(value ?? "")
    .replace(/\*\*/g, "")
    .replace(/__/g, "")
    .replace(/^#{1,6}\s+/gm, "")
    .trim();
}

export function AiText({ children }: { children: unknown }) {
  return (
    <div style={{ whiteSpace: "pre-wrap", fontSize: 22, lineHeight: 1.78 }}>
      {cleanAiText(children)}
    </div>
  );
}

export function LoadingState({ label = "불러오는 중..." }: { label?: string }) {
  return <p style={{ color: "var(--color-text-muted)", fontSize: 22 }}>{label}</p>;
}

export function ErrorState({ message }: { message: string }) {
  return (
    <p style={{ color: "var(--color-bad)", fontSize: 22 }}>
      오류가 발생했습니다: {message}
    </p>
  );
}

export function SeverityPill({ severity }: { severity: 0 | 1 | 2 }) {
  const map = {
    0: { cls: "pill-good", label: "안전" },
    1: { cls: "pill-warn", label: "주의" },
    2: { cls: "pill-bad", label: "위험" },
  } as const;
  const s = map[severity];
  return <span className={`pill ${s.cls}`}>{s.label}</span>;
}

interface JobButtonProps<T> {
  label: string;
  runningLabel?: string;
  progressLabels?: string[];
  storageKey: string;
  onSubmit: () => Promise<{ job_id: string }>;
  renderResult: (result: T) => ReactNode;
  disabled?: boolean;
}

/** Submit-and-poll button: submits a [JOB] endpoint, polls to completion, renders the result inline. */
export function JobButton<T = unknown>({
  label,
  runningLabel = "처리 중... (수 분 소요될 수 있습니다)",
  progressLabels,
  storageKey,
  onSubmit,
  renderResult,
  disabled,
}: JobButtonProps<T>) {
  const { job, isRunning, isDone, isError, submitError, submit, reset } = useJobPoll<T>(storageKey);
  const elapsed = job?.elapsed_seconds ?? 0;
  const phase =
    progressLabels && progressLabels.length > 0
      ? progressLabels[Math.min(progressLabels.length - 1, Math.floor(elapsed / 12))]
      : runningLabel;

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <button
          className="btn btn-primary"
          disabled={disabled || isRunning}
          onClick={() => {
            void submit(onSubmit);
          }}
        >
          {isRunning ? "실행 중..." : label}
        </button>
        {(isDone || isError || submitError) && (
          <button className="btn" onClick={reset}>
            지우기
          </button>
        )}
        {job?.elapsed_seconds != null && (
          <span style={{ fontSize: 20.5, color: "var(--color-text-muted)" }}>
            {job.elapsed_seconds.toFixed(0)}초 경과
          </span>
        )}
      </div>
      {isRunning && (
        <div style={{ marginTop: 10 }}>
          <LoadingState label={phase} />
        </div>
      )}
      {submitError && <div style={{ marginTop: 10 }}><ErrorState message={submitError} /></div>}
      {isError && job?.error && <div style={{ marginTop: 10 }}><ErrorState message={job.error} /></div>}
      {isDone && job?.result != null && <div style={{ marginTop: 10 }}>{renderResult(job.result)}</div>}
    </div>
  );
}
