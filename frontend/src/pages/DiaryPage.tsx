import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { diaryApi, type DiaryEntryIn } from "../api/diary";
import { systemApi } from "../api/system";
import { AiText, ErrorState, JobButton, LoadingState, cleanAiText } from "../components/common";
import GhostTextEditor, { type GhostTextEditorHandle } from "../components/diary/GhostTextEditor";
import { useJobPoll } from "../hooks/useJobPoll";
import type { DiaryEntry, NutrientRecipe } from "../types/api";

const DAY_NAMES = ["일", "월", "화", "수", "목", "금", "토"];

function pad2(n: number) {
  return String(n).padStart(2, "0");
}
function dateStr(y: number, m: number, d: number) {
  return `${y}-${pad2(m)}-${d === undefined ? "" : pad2(d)}`;
}
function todayStr() {
  const t = new Date();
  return dateStr(t.getFullYear(), t.getMonth() + 1, t.getDate());
}

function buildWeeks(year: number, month: number): (number | null)[][] {
  const first = new Date(year, month - 1, 1);
  const daysInMonth = new Date(year, month, 0).getDate();
  const startWeekday = first.getDay();
  const weeks: (number | null)[][] = [];
  let week: (number | null)[] = new Array(startWeekday).fill(null);
  for (let d = 1; d <= daysInMonth; d++) {
    week.push(d);
    if (week.length === 7) {
      weeks.push(week);
      week = [];
    }
  }
  if (week.length > 0) {
    while (week.length < 7) week.push(null);
    weeks.push(week);
  }
  return weeks;
}

function MonthCalendar({
  year,
  month,
  entries,
  harvestDate,
  selected,
  today,
  onSelect,
  onPrev,
  onNext,
}: {
  year: number;
  month: number;
  entries: Record<string, DiaryEntry[]>;
  harvestDate: string | null;
  selected: string;
  today: string;
  onSelect: (d: string) => void;
  onPrev: () => void;
  onNext: () => void;
}) {
  const weeks = useMemo(() => buildWeeks(year, month), [year, month]);

  return (
    <div className="card">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 20, marginBottom: 14 }}>
        <button className="btn" onClick={onPrev}>
          이전
        </button>
        <h3 style={{ fontSize: 22 }}>
          {year}년 {month}월
        </h3>
        <button className="btn" onClick={onNext}>
          다음
        </button>
      </div>
      <table>
        <thead>
          <tr>
            {DAY_NAMES.map((d) => (
              <th key={d} style={{ textAlign: "center", fontSize: 19, color: "var(--color-text-muted)", padding: "4px 0" }}>
                {d}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {weeks.map((week, wi) => (
            <tr key={wi}>
              {week.map((d, di) => {
                if (d === null) return <td key={di} />;
                const ds = dateStr(year, month, d);
                const count = entries[ds]?.length ?? 0;
                const isToday = ds === today;
                const isSelected = ds === selected;
                const isHarvest = ds === harvestDate;
                const dayTags = Array.from(new Set((entries[ds] ?? []).flatMap((e) => e.tags ?? [])));
                const shownTags = dayTags.slice(0, 2);
                const extraCount = dayTags.length - shownTags.length;
                return (
                  <td key={di} style={{ textAlign: "center", padding: 2 }}>
                    <button
                      onClick={() => onSelect(ds)}
                      style={{
                        width: "100%",
                        minHeight: 52,
                        border: isSelected ? "2px solid var(--color-primary)" : "1px solid transparent",
                        borderRadius: 8,
                        background: isToday ? "var(--color-bg-soft)" : "transparent",
                        cursor: "pointer",
                        padding: 4,
                        display: "flex",
                        flexDirection: "column",
                        alignItems: "center",
                        gap: 2,
                      }}
                    >
                      <span style={{ fontSize: 19.5, fontWeight: isToday ? 700 : 400 }}>{d}</span>
                      {isHarvest && <span style={{ fontSize: 16, color: "var(--color-bad)", fontWeight: 700 }}>수확목표</span>}
                      {shownTags.length > 0 ? (
                        <span style={{ fontSize: 14, color: "var(--color-primary)", lineHeight: 1.25 }}>
                          {shownTags.join(", ")}
                          {extraCount > 0 ? ` +${extraCount}` : ""}
                        </span>
                      ) : (
                        count > 0 && (
                          <span style={{ fontSize: 16, color: "var(--color-primary)" }}>
                            {count}건
                          </span>
                        )
                      )}
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HarvestSection() {
  const qc = useQueryClient();
  const statusQ = useQuery({ queryKey: ["harvest-status"], queryFn: diaryApi.harvestStatus });
  const [input, setInput] = useState("");

  useEffect(() => {
    if (statusQ.data?.harvest_date) setInput(statusQ.data.harvest_date);
  }, [statusQ.data?.harvest_date]);

  const setMutation = useMutation({
    mutationFn: (d: string | null) => diaryApi.setHarvestDate(d),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["harvest-status"] }),
  });

  const dd = statusQ.data?.dday;
  const ddColor = dd == null ? undefined : dd > 0 ? (dd > 14 ? "#1971c2" : "#e67700") : dd === 0 ? "#e03131" : "#868e96";
  const ddLabel = dd == null ? "" : dd > 0 ? `D-${dd}` : dd === 0 ? "D-Day" : `D+${Math.abs(dd)}`;

  return (
    <div className="card">
      <h3 style={{ fontSize: 22, marginBottom: 10 }}>수확 목표일</h3>
      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <input
          type="date"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          style={{ padding: 8, borderRadius: 6, border: "1px solid var(--color-border)" }}
        />
        <button className="btn btn-primary" onClick={() => setMutation.mutate(input || null)} disabled={!input}>
          저장
        </button>
        <button
          className="btn"
          onClick={() => {
            setInput("");
            setMutation.mutate(null);
          }}
          disabled={!statusQ.data?.harvest_date}
        >
          목표 해제
        </button>
      </div>

      {statusQ.data?.stage && (
        <div style={{ background: "var(--color-bg-soft)", borderRadius: 8, padding: "11px 15px", marginTop: 14 }}>
          <p style={{ fontWeight: 700, color: "var(--color-good)", marginBottom: 6 }}>현재 단계 · {statusQ.data.stage.stage}</p>
          <p style={{ fontSize: 20, marginBottom: 3 }}>
            <strong>이 시기 관리</strong> — {statusQ.data.stage.manage}
          </p>
          {statusQ.data.stage.consistency_note && (
            <p style={{ fontSize: 19.5, marginTop: 8, color: "var(--color-warn)" }}>
              ⚠ {statusQ.data.stage.consistency_note}
            </p>
          )}
        </div>
      )}
      {dd != null && (
        <div style={{ background: "var(--color-bg-soft)", borderLeft: `5px solid ${ddColor}`, borderRadius: 8, padding: "12px 16px", marginTop: 10, textAlign: "center" }}>
          <div style={{ fontSize: 37, fontWeight: 800, color: ddColor }}>{ddLabel}</div>
          <div style={{ fontSize: 19.5, color: "var(--color-text-muted)", marginTop: 2 }}>
            {dd > 0 ? `수확까지 ${dd}일 남음` : dd === 0 ? "오늘이 수확 목표일입니다!" : `수확 목표일 ${Math.abs(dd)}일 초과`} ({statusQ.data?.harvest_date})
          </div>
        </div>
      )}
    </div>
  );
}

function UpcomingPlanSection() {
  const qc = useQueryClient();
  const planQ = useQuery({ queryKey: ["upcoming-plan"], queryFn: diaryApi.upcomingPlan });
  const plan = planQ.data;
  const { job, isRunning, submitError, submit } = useJobPoll<string>(`job:plan-check-${plan?.date ?? ""}`);
  const feedbackJob = useJobPoll<string>(`job:plan-check-feedback-${plan?.date ?? ""}`);
  const [feedback, setFeedback] = useState("");
  const [showFeedback, setShowFeedback] = useState(false);

  useEffect(() => {
    if (feedbackJob.job?.status === "done") {
      qc.invalidateQueries({ queryKey: ["upcoming-plan"] });
      setFeedback("");
      setShowFeedback(false);
      feedbackJob.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feedbackJob.job]);

  if (!plan) return null;
  const result = plan.cached_result ?? (job?.status === "done" ? (job.result as string) : null);

  return (
    <div className="card">
      <h3 style={{ fontSize: 22, marginBottom: 4 }}>
        다가오는 계획 알림 — {plan.date} ({plan.days_left}일 후)
      </h3>
      <p style={{ fontSize: 20, color: "var(--color-text-muted)", marginBottom: 10 }}>영농일지 기록: {plan.summary}</p>
      {result ? (
        <>
          <AiText>{result}</AiText>
          <div style={{ marginTop: 12 }}>
            {!showFeedback ? (
              <button className="btn" onClick={() => setShowFeedback(true)}>
                이 제안에 의견 남기기
              </button>
            ) : (
              <div>
                <textarea
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                  placeholder="예: 이건 이미 하고 있어요 / 우리 온실은 상황이 달라서 ~로 조정하고 싶어요"
                  rows={2}
                  style={{ width: "100%", padding: 8, borderRadius: 6, border: "1px solid var(--color-border)", resize: "vertical" }}
                />
                <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                  <button
                    className="btn btn-primary"
                    disabled={!feedback.trim() || feedbackJob.isRunning}
                    onClick={() => {
                      void feedbackJob.submit(() =>
                        diaryApi.submitPlanCheckFeedback(plan.date, plan.summary, plan.days_left, feedback.trim()),
                      );
                    }}
                  >
                    {feedbackJob.isRunning ? "반영 중..." : "의견 반영해서 다시 물어보기"}
                  </button>
                  <button className="btn" onClick={() => setShowFeedback(false)} disabled={feedbackJob.isRunning}>
                    취소
                  </button>
                </div>
                {feedbackJob.submitError && <div style={{ marginTop: 10 }}><ErrorState message={feedbackJob.submitError} /></div>}
                {feedbackJob.job?.status === "error" && feedbackJob.job.error && (
                  <div style={{ marginTop: 10 }}><ErrorState message={feedbackJob.job.error} /></div>
                )}
              </div>
            )}
          </div>
        </>
      ) : (
        <>
          <button
            className="btn btn-primary"
            disabled={isRunning}
            onClick={() => {
              void submit(() => diaryApi.submitPlanCheck(plan.date, plan.summary, plan.days_left));
            }}
          >
            {isRunning ? "확인 중..." : "AI 준비사항 확인"}
          </button>
          {submitError && <div style={{ marginTop: 10 }}><ErrorState message={submitError} /></div>}
          {job?.status === "error" && job.error && <div style={{ marginTop: 10 }}><ErrorState message={job.error} /></div>}
        </>
      )}
    </div>
  );
}

function DayEntriesSection({ date, entries }: { date: string; entries: DiaryEntry[] }) {
  const qc = useQueryClient();
  const deleteMutation = useMutation({
    mutationFn: (idx: number) => diaryApi.remove(date, idx),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["diary-all"] }),
  });
  const sorted = [...entries].sort((a, b) => a.time.localeCompare(b.time));

  return (
    <div className="card">
      <h4 style={{ fontSize: 20.5, marginBottom: 10 }}>
        {date} 기록 ({sorted.length}건)
      </h4>
      {sorted.length === 0 ? (
        <p style={{ fontSize: 20, color: "var(--color-text-muted)" }}>이 날의 기록이 없습니다. 아래에서 첫 기록을 추가하세요.</p>
      ) : (
        sorted.map((e, idx) => (
          (() => {
            const tags = e.tags ?? [];
            const pesticides = e.pesticides ?? [];
            const attachments = e.attachments ?? [];
            return (
          <div
            key={idx}
            style={{
              borderLeft: "3px solid var(--color-good)",
              background: "var(--color-bg-soft)",
              borderRadius: "0 8px 8px 0",
              padding: "8px 12px",
              marginBottom: 8,
              display: "flex",
              justifyContent: "space-between",
              gap: 10,
            }}
          >
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 18.5, color: "var(--color-text-muted)" }}>
                  {e.time}
                {tags.length > 0 && (
                  <span style={{ marginLeft: 8 }}>
                    {tags.map((t) => (
                      <span key={t} className="pill" style={{ background: "var(--color-bg)", marginRight: 4, fontSize: 17 }}>
                        {t}
                      </span>
                    ))}
                  </span>
                )}
              </div>
              <div style={{ fontSize: 20, marginTop: 2, whiteSpace: "pre-wrap" }}>{e.content}</div>
              {pesticides.length > 0 && <div style={{ fontSize: 19, color: "var(--color-good)", marginTop: 3 }}>{pesticides.join(", ")}</div>}
              {attachments.length > 0 && (
                <div style={{ marginTop: 6, display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {attachments.map((att, i) => {
                    const stored = typeof att === "string" ? att : att.stored_name;
                    const original = typeof att === "string" ? att.split("_").slice(2).join("_") || att : att.original_name;
                    return (
                      <a key={i} className="btn" href={diaryApi.attachmentUrl(stored)} target="_blank" rel="noreferrer" style={{ fontSize: 18.5 }}>
                        {original}
                      </a>
                    );
                  })}
                </div>
              )}
            </div>
            <button className="btn" onClick={() => deleteMutation.mutate(idx)} style={{ alignSelf: "flex-start" }}>
              삭제
            </button>
          </div>
            );
          })()
        ))
      )}
    </div>
  );
}

function NewEntrySection({ date }: { date: string }) {
  const qc = useQueryClient();
  const [content, setContent] = useState("");
  const [pickedPests, setPickedPests] = useState<string[]>([]);
  const [files, setFiles] = useState<File[]>([]);
  const [resetCount, setResetCount] = useState(0);
  const editorRef = useRef<GhostTextEditorHandle>(null);
  const debounceRef = useRef<number | undefined>(undefined);

  const [detected, setDetected] = useState<{ tags: string[]; diseases: string[]; disease_info: Record<string, { desc: string; pesticides: string[] }> }>({
    tags: [],
    diseases: [],
    disease_info: {},
  });

  const termsQ = useQuery({ queryKey: ["autocomplete-terms"], queryFn: diaryApi.autocompleteTerms, staleTime: Infinity });

  useEffect(() => {
    window.clearTimeout(debounceRef.current);
    if (!content.trim()) {
      setDetected({ tags: [], diseases: [], disease_info: {} });
      return;
    }
    debounceRef.current = window.setTimeout(() => {
      diaryApi.detectTags(content).then(setDetected);
    }, 350);
    return () => window.clearTimeout(debounceRef.current);
  }, [content]);

  const addMutation = useMutation({
    mutationFn: async () => {
      const attachments = await Promise.all(files.map((f) => diaryApi.uploadAttachment(date, f)));
      const body: DiaryEntryIn = { date, content: content.trim(), tags: detected.tags, pesticides: pickedPests, attachments };
      return diaryApi.add(body);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["diary-all"] });
      setContent("");
      setPickedPests([]);
      setFiles([]);
      setResetCount((c) => c + 1);
      editorRef.current?.clear();
    },
  });

  return (
    <div className="card">
      <h4 style={{ fontSize: 20.5, marginBottom: 10 }}>새 기록 추가</h4>
      <GhostTextEditor
        ref={editorRef}
        resetKey={`${date}-${resetCount}`}
        autocompleteTerms={termsQ.data ?? []}
        onChange={setContent}
        placeholder="오늘 작업, 관찰사항, 방제 내용 등을 자유롭게 기록하세요."
      />
      <p style={{ fontSize: 17, color: "var(--color-text-muted)", textAlign: "right", marginTop: 4 }}>
        입력하면 자동완성 제안 · Tab으로 수락
      </p>

      {detected.diseases.length > 0 && (
        <div style={{ marginTop: 10, padding: 12, background: "var(--color-bg-soft)", borderRadius: 8 }}>
          <p style={{ fontSize: 20, marginBottom: 8 }}>
            감지: <strong>{detected.diseases.slice(0, 3).join(", ")}</strong> — 방제 약품을 선택하면 기록에 태그됩니다.
          </p>
          {detected.diseases.map((dis) => (
            <div key={dis} style={{ marginBottom: 8 }}>
              <p style={{ fontSize: 19.5, fontWeight: 600 }}>{dis}</p>
              <p style={{ fontSize: 19, color: "var(--color-text-muted)" }}>{detected.disease_info[dis]?.desc}</p>
              <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 4 }}>
                {(detected.disease_info[dis]?.pesticides ?? []).map((p) => (
                  <label key={p} style={{ fontSize: 19.5, display: "flex", alignItems: "center", gap: 4 }}>
                    <input
                      type="checkbox"
                      checked={pickedPests.includes(p)}
                      onChange={(e) =>
                        setPickedPests((cur) => (e.target.checked ? [...cur, p] : cur.filter((x) => x !== p)))
                      }
                    />
                    {p}
                  </label>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      <div style={{ marginTop: 10 }}>
        <input type="file" multiple onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
      </div>

      <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
        <button className="btn btn-primary" disabled={!content.trim() || addMutation.isPending} onClick={() => addMutation.mutate()}>
          {addMutation.isPending ? "저장 중..." : "기록 추가"}
        </button>
        <a className="btn" href={diaryApi.exportUrl()}>
          전체 CSV 내보내기
        </a>
      </div>
    </div>
  );
}

function MonthSummarySection({ year, month, entries }: { year: number; month: number; entries: Record<string, DiaryEntry[]> }) {
  const prefix = `${year}-${pad2(month)}-`;
  const days = Object.keys(entries)
    .filter((d) => d.startsWith(prefix))
    .sort();
  const total = days.reduce((sum, d) => sum + entries[d].length, 0);
  if (days.length === 0) return null;

  return (
    <details className="card">
      <summary style={{ cursor: "pointer", fontWeight: 600 }}>
        이번 달 기록 ({days.length}일 · {total}건)
      </summary>
      <div style={{ marginTop: 12 }}>
        {days.map((d) => (
          <div key={d} style={{ borderTop: "1px solid var(--color-border)", padding: "8px 0", fontSize: 20 }}>
            <strong>{d}</strong> ({entries[d].length}건)
            {entries[d].map((e, i) => (
              <div key={i} style={{ color: "var(--color-text-muted)", marginLeft: 12 }}>
                {e.time} {e.content}
              </div>
            ))}
          </div>
        ))}
      </div>
    </details>
  );
}

const emptyRecipe: NutrientRecipe = { n: 0, p: 0, k: 0, ca: 0, mg: 0, ec: 0, ph: 0 };

function NutrientSection() {
  const qc = useQueryClient();
  const configQ = useQuery({ queryKey: ["system-config"], queryFn: systemApi.config, staleTime: Infinity });
  const [date, setDate] = useState(todayStr());
  const [recipe, setRecipe] = useState<NutrientRecipe>(emptyRecipe);
  const [symptom, setSymptom] = useState("");

  useEffect(() => {
    if (configQ.data?.today) setDate(configQ.data.today);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [configQ.data?.today]);

  const listQ = useQuery({ queryKey: ["nutrient-recent"], queryFn: () => diaryApi.nutrientList(20) });

  const saveMutation = useMutation({
    mutationFn: () => diaryApi.addNutrient(date, recipe, symptom),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["nutrient-recent"] });
      setRecipe(emptyRecipe);
      setSymptom("");
    },
  });

  const field = (key: keyof NutrientRecipe, label: string, step = 10) => (
    <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 19.5 }}>
      {label}
      <input
        type="number"
        step={step}
        value={recipe[key]}
        onChange={(e) => setRecipe({ ...recipe, [key]: Number(e.target.value) })}
        style={{ padding: 6, borderRadius: 6, border: "1px solid var(--color-border)" }}
      />
    </label>
  );

  return (
    <div className="card">
      <h3 style={{ fontSize: 22, marginBottom: 4 }}>양액 조성 기록</h3>
      <p style={{ fontSize: 19.5, color: "var(--color-text-muted)", marginBottom: 14 }}>
        양액 조성 수치와 관찰된 증상을 날짜별로 기록하고, AI로 성분 부족/과잉 여부를 분석합니다.
      </p>

      <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 19.5, marginBottom: 14, maxWidth: 200 }}>
        기록 날짜
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} style={{ padding: 6, borderRadius: 6, border: "1px solid var(--color-border)" }} />
      </label>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))", gap: 12 }}>
        {field("n", "N (g)")}
        {field("p", "P (g)")}
        {field("k", "K (g)")}
        {field("ca", "Ca (g)")}
        {field("mg", "Mg (g)", 5)}
        {field("ec", "EC (mS/cm)", 0.1)}
        {field("ph", "pH", 0.1)}
      </div>

      <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 19.5, marginTop: 14 }}>
        관찰된 증상 (선택)
        <textarea
          value={symptom}
          onChange={(e) => setSymptom(e.target.value)}
          placeholder="예: 잎끝이 마르고 아랫잎부터 누렇게 변함"
          rows={2}
          style={{ padding: 8, borderRadius: 6, border: "1px solid var(--color-border)", resize: "vertical" }}
        />
      </label>

      <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
        <button className="btn btn-primary" onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
          {saveMutation.isPending ? "저장 중..." : "기록 저장"}
        </button>
      </div>

      <div style={{ marginTop: 10 }}>
        <JobButton
          label="AI 분석 (자동 저장)"
          storageKey="job:nutrient-analyze"
          onSubmit={async () => {
            const { idx } = await diaryApi.addNutrient(date, recipe, symptom);
            qc.invalidateQueries({ queryKey: ["nutrient-recent"] });
            return diaryApi.analyzeNutrient(date, idx, recipe, symptom);
          }}
          renderResult={(result) => {
            qc.invalidateQueries({ queryKey: ["nutrient-recent"] });
            return <AiText>{result}</AiText>;
          }}
        />
      </div>

      {listQ.data && listQ.data.length > 0 && (
        <details style={{ marginTop: 16 }}>
          <summary style={{ cursor: "pointer", fontSize: 20, color: "var(--color-text-muted)" }}>
            최근 양액 조성 기록 ({listQ.data.length}건)
          </summary>
          {listQ.data.map((rn, i) => (
            <div key={i} style={{ borderTop: "1px solid var(--color-border)", padding: "8px 0", fontSize: 20 }}>
              <strong>
                {rn.date} {rn.time}
              </strong>{" "}
              — N{rn.recipe.n}/P{rn.recipe.p}/K{rn.recipe.k}/Ca{rn.recipe.ca}/Mg{rn.recipe.mg} EC{rn.recipe.ec} pH{rn.recipe.ph}
              {rn.symptom && <div style={{ color: "var(--color-text-muted)" }}>증상: {rn.symptom}</div>}
              {rn.ai_analysis && (
                <details style={{ marginTop: 4 }}>
                  <summary style={{ cursor: "pointer", color: "var(--color-primary)", fontSize: 19 }}>AI 분석 결과 보기</summary>
                  <div style={{ whiteSpace: "pre-wrap", marginTop: 6 }}>{cleanAiText(rn.ai_analysis)}</div>
                </details>
              )}
            </div>
          ))}
        </details>
      )}
    </div>
  );
}

export default function DiaryPage() {
  // 캘린더의 "오늘"은 발표용 고정 날짜(tools/demo_clock, /api/system/config의
  // today)를 따른다 — 브라우저의 실제 new Date()를 쓰면 센서·생육·기상은
  // 2026-05-18인데 캘린더만 실제 오늘(7월)을 가리키는 불일치가 생긴다
  // (사용자 확인, 2026-07-10).
  const configQ = useQuery({ queryKey: ["system-config"], queryFn: systemApi.config, staleTime: Infinity });
  const [year, setYear] = useState<number | null>(null);
  const [month, setMonth] = useState<number | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (configQ.data?.today && year === null) {
      const [y, m] = configQ.data.today.split("-").map(Number);
      setYear(y);
      setMonth(m);
      setSelected(configQ.data.today);
    }
  }, [configQ.data, year]);

  const entriesQ = useQuery({ queryKey: ["diary-all"], queryFn: diaryApi.all });

  const prevMonth = () => {
    if (month === null || year === null) return;
    if (month === 1) {
      setYear(year - 1);
      setMonth(12);
    } else setMonth(month - 1);
  };
  const nextMonth = () => {
    if (month === null || year === null) return;
    if (month === 12) {
      setYear(year + 1);
      setMonth(1);
    } else setMonth(month + 1);
  };

  const harvestStatusQ = useQuery({ queryKey: ["harvest-status"], queryFn: diaryApi.harvestStatus });

  if (entriesQ.isLoading || year === null || month === null || selected === null) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <HarvestSection />
        <LoadingState />
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <HarvestSection />

      <MonthCalendar
        year={year}
        month={month}
        entries={entriesQ.data ?? {}}
        harvestDate={harvestStatusQ.data?.harvest_date ?? null}
        selected={selected}
        today={configQ.data!.today}
        onSelect={setSelected}
        onPrev={prevMonth}
        onNext={nextMonth}
      />

      <UpcomingPlanSection />

      <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 19.5, maxWidth: 200 }}>
        날짜 선택
        <input type="date" value={selected} onChange={(e) => setSelected(e.target.value)} style={{ padding: 8, borderRadius: 6, border: "1px solid var(--color-border)" }} />
      </label>

      <DayEntriesSection date={selected} entries={entriesQ.data?.[selected] ?? []} />
      <NewEntrySection date={selected} />
      <MonthSummarySection year={year} month={month} entries={entriesQ.data ?? {}} />
      <NutrientSection />
    </div>
  );
}
