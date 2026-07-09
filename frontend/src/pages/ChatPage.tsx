import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { chatApi } from "../api/chat";
import { pricesApi } from "../api/prices";
import { AiText, JobButton, LoadingState, cleanAiText } from "../components/common";
import { useJobPoll } from "../hooks/useJobPoll";

function fmtWon(n: number | null | undefined) {
  return n ? `${n.toLocaleString()}원` : "—";
}

const CHAT_EXAMPLES = [
  "지금 기상 파악해서 조치 알려줘",
  "현재 온실 상태를 보고 환기 열어도 되는지 판단해줘",
  "오늘 VPD가 높은 편인지 확인하고 조치 알려줘",
  "지금 습도 기준으로 병해 위험이 있는지 알려줘",
  "CO2 시비를 지금 해도 되는지 판단해줘",
  "오늘 야간 온도는 몇 도로 맞추면 좋아?",
  "최근 생육 데이터 기준으로 이상한 점 찾아줘",
  "가격 상황 보고 오늘 출하가 나은지 알려줘",
  "내 최근 판단 기록을 보고 반복되는 문제를 정리해줘",
];

function pickExample(input: string) {
  const q = input.trim();
  if (!q) return CHAT_EXAMPLES[0];
  return CHAT_EXAMPLES.find((ex) => ex.includes(q) || ex.startsWith(q)) ?? CHAT_EXAMPLES[0];
}

function ImageDiagnosisSection() {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [question, setQuestion] = useState("");
  const [preview, setPreview] = useState<string | null>(null);

  return (
    <div className="card">
      <button
        onClick={() => setOpen((v) => !v)}
        style={{ background: "none", border: "none", padding: 0, font: "inherit", cursor: "pointer", display: "flex", justifyContent: "space-between", width: "100%" }}
      >
        <span style={{ fontWeight: 600 }}>이미지 업로드 분석(병해 사진)</span>
        <span style={{ color: "var(--color-text-muted)" }}>{open ? "접기" : "펼치기"}</span>
      </button>
      {open && (
        <div style={{ marginTop: 14 }}>
          <input
            type="file"
            accept="image/jpeg,image/png"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setFile(f);
              setPreview(f ? URL.createObjectURL(f) : null);
            }}
          />
          <input
            type="text"
            placeholder="사진에 대해 질문 (선택) — 예: 이 잎에 어떤 병이 생긴 건가요?"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            style={{ display: "block", marginTop: 10, width: "100%", padding: 8, borderRadius: 6, border: "1px solid var(--color-border)" }}
          />
          {preview && <img src={preview} alt="" style={{ maxWidth: 240, marginTop: 10, borderRadius: 8 }} />}
          <div style={{ marginTop: 12 }}>
            <JobButton
              label="이미지 분석"
              storageKey="job:image-diagnosis"
              disabled={!file}
              onSubmit={() => chatApi.diagnoseImage(file!, question)}
              renderResult={(result) => <AiText>{result}</AiText>}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function PriceInfoSection() {
  const [open, setOpen] = useState(false);
  const gradesQ = useQuery({ queryKey: ["chat-price-grades"], queryFn: pricesApi.grades, enabled: open });
  const cycleQ = useQuery({
    queryKey: ["chat-price-cycle"],
    queryFn: () => pricesApi.originMarketCycle(180, 3),
    enabled: open,
  });

  return (
    <div className="card">
      <button
        onClick={() => setOpen((v) => !v)}
        style={{ background: "none", border: "none", padding: 0, font: "inherit", cursor: "pointer", display: "flex", justifyContent: "space-between", width: "100%" }}
      >
        <span style={{ fontWeight: 600 }}>가격 정보 (참고)</span>
        <span style={{ color: "var(--color-text-muted)" }}>{open ? "접기" : "펼치기"}</span>
      </button>
      {open && (
        <div style={{ marginTop: 14 }}>
          {gradesQ.isLoading ? (
            <LoadingState />
          ) : (
            <>
              <p style={{ fontSize: 19.5, color: "var(--color-text-muted)", marginBottom: 10 }}>
                {gradesQ.data?.date} · {gradesQ.data?.market ?? "—"} · 4kg 기준 (aT 도매시장 실시간 경매정보)
              </p>
              {gradesQ.data?.market === "—" ? (
                <p style={{ fontSize: 19.5, color: "var(--color-warn)", marginBottom: 16 }}>
                  ⚠ 지금은 가격을 조회할 수 없습니다 — aT 실시간 API의 일일 조회 한도를 초과했을 수 있습니다. 잠시 후 다시 열어보세요.
                </p>
              ) : (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10, marginBottom: 16 }}>
                  {(["상", "중", "하"] as const).map((g) => (
                    <div key={g} className="card" style={{ padding: "10px 14px" }}>
                      <div style={{ fontSize: 19, color: "var(--color-text-muted)" }}>{g}품</div>
                      <div style={{ fontSize: 22, fontWeight: 700 }}>
                        {gradesQ.data?.[g]?.price ? `${gradesQ.data[g].price_str}원` : "—"}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {cycleQ.data && cycleQ.data.market_summary.length > 0 && (
                <>
                  <div style={{ fontWeight: 600, marginBottom: 6 }}>시장별 최근 평균가 (최근 180일 누적)</div>
                  <div style={{ display: "grid", gap: 6, marginBottom: 10 }}>
                    {cycleQ.data.market_summary.slice(0, 6).map((m) => (
                      <div key={m["도매시장"]} style={{ display: "flex", justifyContent: "space-between", fontSize: 20 }}>
                        <span>{m["도매시장"]}</span>
                        <span>
                          {fmtWon(m["평균가"])} <span style={{ color: "var(--color-text-muted)" }}>({m["건수"]}건)</span>
                        </span>
                      </div>
                    ))}
                  </div>
                </>
              )}
              <p style={{ fontSize: 19, color: "var(--color-text-muted)" }}>
                산지별 프리미엄·물류비 비교, 판매 시점 제안 등 자세한 건 아래 채팅에 물어보세요 — 예: "가격 상황 보고 오늘 출하가 나은지 알려줘"
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function NcpmsSection() {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<string>("");
  const [detail, setDetail] = useState<import("../types/api").NcpmsDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const searchQ = useQuery({ queryKey: ["ncpms-search"], queryFn: () => chatApi.ncpmsSearch(), enabled: open });

  return (
    <div className="card">
      <button
        onClick={() => setOpen((v) => !v)}
        style={{ background: "none", border: "none", padding: 0, font: "inherit", cursor: "pointer", display: "flex", justifyContent: "space-between", width: "100%" }}
      >
        <span style={{ fontWeight: 600 }}>병해충 도감 (NCPMS)</span>
        <span style={{ color: "var(--color-text-muted)" }}>{open ? "접기" : "펼치기"}</span>
      </button>
      {open && (
        <div style={{ marginTop: 14 }}>
          {searchQ.isLoading ? (
            <LoadingState />
          ) : searchQ.data && searchQ.data.length > 0 ? (
            <>
              <div style={{ display: "flex", gap: 10 }}>
                <select value={selected} onChange={(e) => setSelected(e.target.value)} style={{ flex: 1, padding: 8, borderRadius: 6, border: "1px solid var(--color-border)" }}>
                  <option value="">병해충 선택</option>
                  {searchQ.data.map((d) => (
                    <option key={d.sickKey} value={d.sickKey}>
                      {d.name} ({d.kind})
                    </option>
                  ))}
                </select>
                <button
                  className="btn btn-primary"
                  disabled={!selected}
                  onClick={async () => {
                    setError(null);
                    try {
                      setDetail(await chatApi.ncpmsDetail(selected));
                    } catch (e) {
                      setError((e as Error).message);
                    }
                  }}
                >
                  상세 조회
                </button>
              </div>
              {error && <p style={{ color: "var(--color-bad)", fontSize: 19.5, marginTop: 8 }}>{error}</p>}
              {detail && (
                <div style={{ marginTop: 14 }}>
                  <h4 style={{ fontSize: 22 }}>
                    {detail.name} <span style={{ fontSize: 19.5, color: "var(--color-text-muted)", fontWeight: 400 }}>{detail.crop}</span>
                  </h4>
                  {detail.images.length > 0 && (
                    <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                      {detail.images.slice(0, 3).map((src, i) => (
                        <img key={i} src={src} alt="" style={{ width: 180, borderRadius: 8 }} />
                      ))}
                    </div>
                  )}
                  {([
                    ["증상", detail.symptoms],
                    ["발생조건", detail.condition],
                    ["방제법", detail.prevention],
                    ["화학적 방제", detail.chemical],
                  ] as const).map(
                    ([label, value]) =>
                      value && (
                        <p key={label} style={{ fontSize: 20, marginTop: 8 }}>
                          <strong>{label}</strong>
                          <br />
                          {value.split(/<br\s*\/?>/i).map((line, i, arr) => (
                            <span key={i}>
                              {line}
                              {i < arr.length - 1 && <br />}
                            </span>
                          ))}
                        </p>
                      ),
                  )}
                  <p style={{ fontSize: 19, color: "var(--color-text-muted)", marginTop: 8 }}>
                    출처: 국가농작물병해충관리시스템(NCPMS)
                  </p>
                </div>
              )}
            </>
          ) : (
            <p style={{ fontSize: 20, color: "var(--color-text-muted)" }}>
              NCPMS 도감을 쓰려면 .env에 NCPMS_API_KEY를 추가하세요 (ncpms.rda.go.kr → OpenAPI 활용신청).
            </p>
          )}
        </div>
      )}
    </div>
  );
}

interface ChatMsg {
  role: "user" | "assistant";
  content: string;
}

const HISTORY_KEY = "chat:history";
const PENDING_KEY = "chat:pending-question";

function loadHistory(): ChatMsg[] {
  try {
    return JSON.parse(sessionStorage.getItem(HISTORY_KEY) ?? "[]");
  } catch {
    return [];
  }
}

// Navigating between SPA routes unmounts this component without a full page
// reload — session-scoped state (history, which question a running job
// belongs to) is kept in sessionStorage so a reply that finishes while the
// user is on another tab isn't silently dropped when they come back.
function FreeChatSection() {
  const [history, setHistory] = useState<ChatMsg[]>(loadHistory);
  const [input, setInput] = useState("");
  const [placeholderIndex, setPlaceholderIndex] = useState(0);
  const { job, isRunning, submit, reset } = useJobPoll<string>("job:chat-message");
  const pendingRef = useRef<string | null>(sessionStorage.getItem(PENDING_KEY));

  useEffect(() => {
    sessionStorage.setItem(HISTORY_KEY, JSON.stringify(history));
  }, [history]);

  const setPending = (q: string | null) => {
    pendingRef.current = q;
    if (q) sessionStorage.setItem(PENDING_KEY, q);
    else sessionStorage.removeItem(PENDING_KEY);
  };

  const send = async () => {
    if (!input.trim() || isRunning) return;
    const q = input.trim();
    setHistory((h) => [...h, { role: "user", content: q }]);
    setPending(q);
    setInput("");
    const jobId = await submit(() => chatApi.sendMessage(q));
    if (!jobId) {
      setHistory((h) => [...h, { role: "assistant", content: "오류: 메시지를 전송하지 못했습니다. 잠시 후 다시 시도하세요." }]);
      setPending(null);
    }
  };

  useEffect(() => {
    if (!pendingRef.current) return;
    if (job?.status === "done") {
      setHistory((h) => [...h, { role: "assistant", content: String(job.result ?? "") }]);
      setPending(null);
      reset();
    } else if (job?.status === "error") {
      setHistory((h) => [...h, { role: "assistant", content: `오류: ${job.error}` }]);
      setPending(null);
      reset();
    }
  }, [job, reset]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setPlaceholderIndex((i) => (i + 1) % CHAT_EXAMPLES.length);
    }, 3500);
    return () => window.clearInterval(timer);
  }, []);

  const suggestion = pickExample(input);

  return (
    <div className="card">
      <h3 style={{ fontSize: 22, marginBottom: 4 }}>AI 상담 (MCP 에이전트)</h3>
      <p style={{ fontSize: 19.5, color: "var(--color-text-muted)", marginBottom: 14 }}>
        현재 센서값·외기 조건·지식베이스에 더해, 필요시 Ollama가 센서·생육·진단이력·가격 도구를 직접 호출해 답변합니다.
      </p>

      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 14, maxHeight: 420, overflowY: "auto" }}>
        {history.map((m, i) => (
          <div
            key={i}
            style={{
              alignSelf: m.role === "user" ? "flex-end" : "flex-start",
              background: m.role === "user" ? "var(--color-primary)" : "var(--color-bg-soft)",
              color: m.role === "user" ? "white" : "var(--color-text)",
              padding: "8px 14px",
              borderRadius: 12,
              maxWidth: "80%",
              whiteSpace: "pre-wrap",
              fontSize: 20,
            }}
          >
            {m.role === "assistant" ? cleanAiText(m.content) : m.content}
          </div>
        ))}
        {isRunning && <LoadingState label="MCP 도구 호출 + LLM 추론 중... (수 분 소요될 수 있습니다)" />}
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
        {CHAT_EXAMPLES.slice(0, 5).map((ex) => (
          <button
            key={ex}
            type="button"
            className="btn"
            disabled={isRunning}
            onClick={() => setInput(ex)}
            style={{ fontSize: 19.5 }}
          >
            {ex}
          </button>
        ))}
      </div>

      <div style={{ display: "flex", gap: 8 }}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Tab") {
              e.preventDefault();
              setInput(suggestion);
            } else if (e.key === "Enter") send();
          }}
          placeholder={CHAT_EXAMPLES[placeholderIndex]}
          disabled={isRunning}
          style={{ flex: 1, padding: 10, borderRadius: 8, border: "1px solid var(--color-border)" }}
        />
        <button className="btn btn-primary" onClick={send} disabled={isRunning || !input.trim()}>
          전송
        </button>
      </div>
      <p style={{ marginTop: 7, fontSize: 19, color: "var(--color-text-muted)" }}>
        Tab 자동완성: {suggestion}
      </p>
      {history.length > 0 && (
        <button className="btn" style={{ marginTop: 10 }} onClick={() => setHistory([])}>
          대화 초기화
        </button>
      )}
    </div>
  );
}

export default function ChatPage() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <ImageDiagnosisSection />
      <NcpmsSection />
      <PriceInfoSection />
      <FreeChatSection />
    </div>
  );
}
