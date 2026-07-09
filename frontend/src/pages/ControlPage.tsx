import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { controlApi, type ControlLogIn } from "../api/control";
import { AiText, JobButton, LoadingState } from "../components/common";
import type { DiagnosisRecord } from "../types/api";

interface DiagnosisJobResult {
  vpd: number;
  response: string;
  record: DiagnosisRecord;
}

interface AdviceJobResult {
  situation: string;
  recommendation: string;
  generated_at: string;
  sensor: Record<string, unknown>;
  outdoor?: Record<string, unknown> | null;
}

interface DiagnosisWithAdviceJobResult {
  diagnosis: DiagnosisJobResult;
  advice: AdviceJobResult;
}

function computeTempAnalysis(records: DiagnosisRecord[]) {
  const today = new Date().toISOString().slice(0, 10);
  const dayT: number[] = [];
  const nightT: number[] = [];
  for (const r of records) {
    if (!r.timestamp.startsWith(today)) continue;
    const hour = Number(r.timestamp.slice(11, 13));
    const t = Number(r.sensor_input?.temp || 0);
    if (t > 0) (hour >= 6 && hour < 18 ? dayT : nightT).push(t);
  }
  if (dayT.length > 0) {
    const dayAvg = Math.round((dayT.reduce((a, b) => a + b, 0) / dayT.length) * 10) / 10;
    const nightAvg = nightT.length ? Math.round((nightT.reduce((a, b) => a + b, 0) / nightT.length) * 10) / 10 : null;
    return {
      hasDayData: true,
      dayAvg,
      dayMax: Math.round(Math.max(...dayT) * 10) / 10,
      dayMin: Math.round(Math.min(...dayT) * 10) / 10,
      nightAvg,
      recNight: Math.round(Math.max(16, Math.min(22, dayAvg - 5)) * 10) / 10,
    };
  }
  return { hasDayData: false, dayAvg: 0, dayMax: 0, dayMin: 0, nightAvg: null, recNight: 19 };
}

const ctrlLogEmpty: ControlLogIn = { target: "천창", action: "켬", setval: "", zone: "전체", reason: "", result: "" };

export default function ControlPage() {
  const qc = useQueryClient();

  const historyQ = useQuery({ queryKey: ["diagnosis-history"], queryFn: () => controlApi.diagnosisHistory(10) });
  const adviceLogQ = useQuery({ queryKey: ["advice-log"], queryFn: () => controlApi.adviceLog(50) });
  const autoStatusQ = useQuery({
    queryKey: ["auto-diagnosis-status"],
    queryFn: controlApi.autoStatus,
    refetchInterval: 15_000,
  });
  const emailStatusQ = useQuery({ queryKey: ["email-status"], queryFn: controlApi.emailStatus, refetchInterval: 30_000 });
  const ctrlLogQ = useQuery({ queryKey: ["control-log"], queryFn: controlApi.getLog });

  const [interval, setIntervalMin] = useState(30);
  const autoMutation = useMutation({
    mutationFn: (enabled: boolean) => controlApi.putAutoSettings({ enabled, interval_minutes: interval }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["auto-diagnosis-status"] }),
  });
  const emailTestMutation = useMutation({
    mutationFn: controlApi.emailTest,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["email-status"] }),
  });

  const [advResponse, setAdvResponse] = useState("");
  const respondMutation = useMutation({
    mutationFn: ({ advice, response }: { advice: AdviceJobResult; response: string }) =>
      controlApi.adviceResponse(advice as unknown as Record<string, unknown>, response),
    onSuccess: () => {
      setAdvResponse("");
      qc.invalidateQueries({ queryKey: ["advice-log"] });
      qc.invalidateQueries({ queryKey: ["diagnosis-history"] });
    },
  });

  const [ctrlForm, setCtrlForm] = useState<ControlLogIn>(ctrlLogEmpty);
  const ctrlMutation = useMutation({
    mutationFn: (body: ControlLogIn) => controlApi.postLog(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["control-log"] });
      setCtrlForm(ctrlLogEmpty);
    },
  });

  const tempAnalysis = useMemo(() => computeTempAnalysis(historyQ.data ?? []), [historyQ.data]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div className="card">
        <h3 style={{ fontSize: 22, marginBottom: 10 }}>자동 진단</h3>
        <p style={{ fontSize: 19.5, color: "var(--color-text-muted)", marginBottom: 12 }}>
          설정 간격마다 센서 동기화 → RAG 문서 기반 LLM 진단을 자동 실행합니다.
        </p>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 20 }}>
            <input
              type="checkbox"
              checked={autoStatusQ.data?.enabled ?? false}
              onChange={(e) => autoMutation.mutate(e.target.checked)}
            />
            자동 진단 켜기
          </label>
          <select
            value={interval}
            onChange={(e) => {
              const v = Number(e.target.value);
              setIntervalMin(v);
              if (autoStatusQ.data?.enabled) controlApi.putAutoSettings({ enabled: true, interval_minutes: v }).then(() => qc.invalidateQueries({ queryKey: ["auto-diagnosis-status"] }));
            }}
            style={{ padding: 6, borderRadius: 6, border: "1px solid var(--color-border)" }}
          >
            {[30, 60, 90].map((m) => (
              <option key={m} value={m}>
                {m}분
              </option>
            ))}
          </select>
          {autoStatusQ.data?.last_run_at && (
            <span style={{ fontSize: 19.5, color: "var(--color-text-muted)" }}>
              마지막 실행: {autoStatusQ.data.last_run_at.slice(0, 19)}
            </span>
          )}
        </div>
      </div>

      <div className="card">
        <h3 style={{ fontSize: 22, marginBottom: 10 }}>이메일 경보</h3>
        {emailStatusQ.data?.in_cooldown ? (
          <p style={{ fontSize: 20 }}>쿨다운 중 ({emailStatusQ.data.cooldown_remaining_min}분 남음)</p>
        ) : (
          <p style={{ fontSize: 20, color: "var(--color-text-muted)" }}>정상 범위 — 경보 없음</p>
        )}
        <button className="btn" style={{ marginTop: 10 }} onClick={() => emailTestMutation.mutate()} disabled={emailTestMutation.isPending}>
          {emailTestMutation.isPending ? "발송 중..." : "지금 테스트 발송"}
        </button>
        {emailTestMutation.isSuccess && <span style={{ marginLeft: 10, fontSize: 19.5, color: "var(--color-good)" }}>발송됨</span>}
        {emailTestMutation.isError && <span style={{ marginLeft: 10, fontSize: 19.5, color: "var(--color-bad)" }}>{(emailTestMutation.error as Error).message}</span>}
      </div>

      <div className="card">
        <h3 style={{ fontSize: 22, marginBottom: 10 }}>온도 관리 분석</h3>
        {tempAnalysis.hasDayData ? (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 12 }}>
              <div className="card" style={{ padding: "10px 14px" }}>
                <div style={{ fontSize: 19, color: "var(--color-text-muted)" }}>주간 평균 온도</div>
                <div style={{ fontSize: 22, fontWeight: 600 }}>{tempAnalysis.dayAvg}℃</div>
                <div style={{ fontSize: 19, color: "var(--color-text-muted)" }}>최고 {tempAnalysis.dayMax}℃ / 최저 {tempAnalysis.dayMin}℃</div>
              </div>
              <div className="card" style={{ padding: "10px 14px" }}>
                <div style={{ fontSize: 19, color: "var(--color-text-muted)" }}>권장 야간 온도</div>
                <div style={{ fontSize: 22, fontWeight: 600 }}>{tempAnalysis.recNight}℃</div>
                <div style={{ fontSize: 19, color: "var(--color-text-muted)" }}>주야간 5℃ 차 기준</div>
              </div>
              <div className="card" style={{ padding: "10px 14px" }}>
                <div style={{ fontSize: 19, color: "var(--color-text-muted)" }}>현재 야간 평균</div>
                <div style={{ fontSize: 22, fontWeight: 600 }}>{tempAnalysis.nightAvg ?? "—"}℃</div>
                <div style={{ fontSize: 19, color: "var(--color-text-muted)" }}>오늘 18시 이후 측정치</div>
              </div>
            </div>
            <p style={{ fontSize: 20 }}>
              {tempAnalysis.dayAvg > 30
                ? `주간 고온(${tempAnalysis.dayAvg}℃) 감지. 야간 ${tempAnalysis.recNight}℃ 이하 목표. 관수·환기 우선 점검.`
                : tempAnalysis.dayAvg >= 22
                  ? `주간 온도 적정(${tempAnalysis.dayAvg}℃). 야간 ${tempAnalysis.recNight}℃ 목표 — 주야간 5℃ 차 유지 시 착과율 향상.`
                  : `주간 저온(${tempAnalysis.dayAvg}℃). 야간 최소 16℃ 이상 유지 필요.`}
            </p>
          </>
        ) : (
          <p style={{ fontSize: 20, color: "var(--color-text-muted)" }}>
            주간(6~18시) 진단 기록이 없습니다. 낮 시간에 진단을 실행하면 야간 온도 권고가 자동으로 계산됩니다.
          </p>
        )}
      </div>

      <div className="card">
        <h3 style={{ fontSize: 23, marginBottom: 6 }}>현재 상태 진단 및 실행할 조치 추천</h3>
        <p style={{ fontSize: 20, color: "var(--color-text-muted)", marginBottom: 14 }}>
          센서·외기·RAG 문서를 종합해 현재 상태를 진단하고, 바로 실행할 조치 1가지를 제안합니다.
        </p>
        <JobButton<DiagnosisWithAdviceJobResult>
          label="진단하고 조치 추천 받기"
          storageKey="job:diagnosis-with-advice"
          progressLabels={[
            "지금 온실 센서값을 불러오는 중입니다.",
            "지금 외기 조건과 기상 데이터를 분석하는 중입니다.",
            "지금 RAG 문서에서 관련 재배 기준을 찾는 중입니다.",
            "지금 LLM이 온도·습도·CO2·일사 상태를 진단하는 중입니다.",
            "지금 실행할 조치 1가지를 추천하는 중입니다.",
          ]}
          onSubmit={() => controlApi.submitDiagnosisWithAdvice()}
          renderResult={(result) => (
            <div>
              <p style={{ fontSize: 20.5, fontWeight: 800, color: "var(--color-good)" }}>
                진단 완료 — VPD {result.diagnosis.vpd} kPa ({result.diagnosis.record.timestamp})
              </p>
              <div style={{ marginTop: 8 }}>
                {result.diagnosis.response || result.diagnosis.record?.llm_response ? (
                  <AiText>{result.diagnosis.response || result.diagnosis.record.llm_response}</AiText>
                ) : (
                  <p style={{ color: "var(--color-bad)", fontSize: 20.5 }}>
                    LLM이 빈 응답을 반환했습니다. 지우기를 누른 뒤 다시 진단해 주세요.
                  </p>
                )}
              </div>
              <div className="card" style={{ marginTop: 14, background: "var(--color-good-bg)", borderColor: "rgba(5, 150, 105, 0.28)" }}>
                <p style={{ fontSize: 20, color: "var(--color-text-muted)", marginBottom: 5 }}>추천 조치 · {result.advice.generated_at}</p>
                <p style={{ fontSize: 22, marginBottom: 4 }}>
                  <strong>상황:</strong> {result.advice.situation}
                </p>
                <p style={{ fontSize: 22 }}>
                  <strong>제안:</strong> {result.advice.recommendation}
                </p>
                <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
                  <button className="btn btn-primary" onClick={() => respondMutation.mutate({ advice: result.advice, response: "y" })}>
                    허용
                  </button>
                  <button className="btn" onClick={() => respondMutation.mutate({ advice: result.advice, response: "n" })}>
                    거부
                  </button>
                  <input
                    type="text"
                    placeholder="직접 조치 내용을 입력..."
                    value={advResponse}
                    onChange={(e) => setAdvResponse(e.target.value)}
                    style={{ flex: "1 1 260px", padding: 9, borderRadius: 999, border: "1px solid var(--color-border)" }}
                  />
                  <button className="btn" disabled={!advResponse} onClick={() => respondMutation.mutate({ advice: result.advice, response: advResponse })}>
                    직접 입력 저장
                  </button>
                </div>
              </div>
              {result.diagnosis.record.sources.length > 0 && (
                <details style={{ marginTop: 10 }}>
                  <summary style={{ cursor: "pointer", fontSize: 19.5, color: "var(--color-text-muted)" }}>RAG 출처</summary>
                  <ul>
                    {result.diagnosis.record.sources.map((s, i) => (
                      <li key={i} style={{ fontSize: 19.5 }}>
                        {s}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}
        />
        <div style={{ marginTop: 4 }}>
          <button className="btn" style={{ marginTop: 10 }} onClick={() => qc.invalidateQueries({ queryKey: ["diagnosis-history"] })}>
            판단 기록 새로고침
          </button>
        </div>
      </div>

      {(() => {
        const rejected = (adviceLogQ.data ?? []).filter((entry) => {
          const resp = String((entry as Record<string, unknown>).farmer_response ?? "");
          return resp && resp !== "y";
        });
        if (rejected.length === 0) return null;
        return (
          <div className="card" style={{ borderColor: "var(--color-warn)" }}>
            <h3 style={{ fontSize: 22, marginBottom: 4 }}>거부한 조치 — 검토 대기 ({rejected.length}건)</h3>
            <p style={{ fontSize: 19.5, color: "var(--color-text-muted)", marginBottom: 12 }}>
              농장주가 거부한 AI 조치입니다. 규칙이 실제 상황과 맞지 않았다면, 이 목록을 참고해 지식베이스나
              판단 로직을 보완할 수 있습니다.
            </p>
            {[...rejected].reverse().map((entry, i) => {
              const e = entry as Record<string, unknown>;
              const resp = String(e.farmer_response ?? "");
              return (
                <div key={i} style={{ borderTop: "1px solid var(--color-border)", padding: "10px 0", fontSize: 20 }}>
                  <strong>{String(e.responded_at ?? "").slice(0, 16)}</strong>
                  <div style={{ color: "var(--color-text-muted)" }}>상황: {String(e.situation ?? "")}</div>
                  <div style={{ color: "var(--color-text-muted)" }}>제안: {String(e.recommendation ?? "")}</div>
                  {resp !== "n" && <div style={{ color: "var(--color-warn)" }}>농가 의견: {resp}</div>}
                </div>
              );
            })}
          </div>
        );
      })()}

      <div className="card">
        <h3 style={{ fontSize: 22, marginBottom: 10 }}>조치 응답 이력</h3>
        {adviceLogQ.data && adviceLogQ.data.length > 0 && (
          <details style={{ marginTop: 14 }}>
            <summary style={{ cursor: "pointer", fontSize: 19.5, color: "var(--color-text-muted)" }}>
              조치 응답 이력 ({adviceLogQ.data.length}건)
            </summary>
            {[...adviceLogQ.data].reverse().map((entry, i) => {
              const e = entry as Record<string, unknown>;
              const resp = String(e.farmer_response ?? "");
              return (
                <div key={i} style={{ borderTop: "1px solid var(--color-border)", padding: "8px 0", fontSize: 19.5 }}>
                  <strong>{String(e.responded_at ?? "").slice(0, 16)}</strong>
                  <div style={{ color: "var(--color-text-muted)" }}>상황: {String(e.situation ?? "")}</div>
                  <div style={{ color: "var(--color-text-muted)" }}>제안: {String(e.recommendation ?? "")}</div>
                  <div style={{ color: "var(--color-text-muted)" }}>응답: {resp === "y" ? "실행" : resp === "n" ? "미실행" : resp}</div>
                </div>
              );
            })}
          </details>
        )}
        {(!adviceLogQ.data || adviceLogQ.data.length === 0) && (
          <p style={{ fontSize: 20, color: "var(--color-text-muted)" }}>아직 조치 응답 이력이 없습니다.</p>
        )}
      </div>

      <div className="card">
        <h3 style={{ fontSize: 22, marginBottom: 10 }}>판단 기록 (최근 10건)</h3>
        {historyQ.isLoading ? (
          <LoadingState />
        ) : historyQ.data && historyQ.data.length > 0 ? (
          <div className="overflow-x">
            <table>
              <thead>
                <tr style={{ textAlign: "left", color: "var(--color-text-muted)", fontSize: 19.5 }}>
                  <th>시간</th>
                  <th>온도(℃)</th>
                  <th>습도(%)</th>
                  <th>CO2(ppm)</th>
                  <th>VPD(kPa)</th>
                  <th>외기온(℃)</th>
                  <th>농민 조치</th>
                </tr>
              </thead>
              <tbody>
                {historyQ.data.map((r, i) => (
                  <tr key={i} style={{ borderTop: "1px solid var(--color-border)", fontSize: 20 }}>
                    <td style={{ padding: "6px 0" }}>{r.timestamp}</td>
                    <td>{r.sensor_input.temp}</td>
                    <td>{r.sensor_input.rh}</td>
                    <td>{r.sensor_input.co2}</td>
                    <td>{r.vpd_calculated}</td>
                    <td>{(r.outdoor as { outdoor_temp?: number })?.outdoor_temp ?? "—"}</td>
                    <td>{r.farmer_action ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p style={{ fontSize: 20, color: "var(--color-text-muted)" }}>아직 판단 기록이 없습니다.</p>
        )}
      </div>

      <div className="card">
        <h3 style={{ fontSize: 22, marginBottom: 10 }}>센서 제어 로그</h3>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            ctrlMutation.mutate(ctrlForm);
          }}
          style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 14, marginBottom: 16 }}
        >
          <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 19.5 }}>
            제어 대상
            <select value={ctrlForm.target} onChange={(e) => setCtrlForm({ ...ctrlForm, target: e.target.value })} style={{ padding: 6, borderRadius: 6, border: "1px solid var(--color-border)" }}>
              {["천창", "측창", "난방기", "냉방기", "환풍기", "포그", "CO2공급기", "차광막", "기타"].map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 19.5 }}>
            조치 내용
            <select value={ctrlForm.action} onChange={(e) => setCtrlForm({ ...ctrlForm, action: e.target.value })} style={{ padding: 6, borderRadius: 6, border: "1px solid var(--color-border)" }}>
              {["켬", "끔", "개방", "폐쇄", "설정값 변경", "점검", "기타"].map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 19.5 }}>
            설정값 (선택)
            <input type="text" placeholder="예: 25℃, 50%" value={ctrlForm.setval} onChange={(e) => setCtrlForm({ ...ctrlForm, setval: e.target.value })} style={{ padding: 6, borderRadius: 6, border: "1px solid var(--color-border)" }} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 19.5 }}>
            구역
            <select value={ctrlForm.zone} onChange={(e) => setCtrlForm({ ...ctrlForm, zone: e.target.value })} style={{ padding: 6, borderRadius: 6, border: "1px solid var(--color-border)" }}>
              {["전체", "A", "B", "C"].map((z) => (
                <option key={z} value={z}>
                  {z}
                </option>
              ))}
            </select>
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 19.5 }}>
            조치 이유
            <input type="text" placeholder="예: VPD 1.8kPa 초과" value={ctrlForm.reason} onChange={(e) => setCtrlForm({ ...ctrlForm, reason: e.target.value })} style={{ padding: 6, borderRadius: 6, border: "1px solid var(--color-border)" }} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 19.5 }}>
            결과 (선택)
            <input type="text" placeholder="예: 온도 2℃ 하강 확인" value={ctrlForm.result} onChange={(e) => setCtrlForm({ ...ctrlForm, result: e.target.value })} style={{ padding: 6, borderRadius: 6, border: "1px solid var(--color-border)" }} />
          </label>
          <div style={{ gridColumn: "1 / -1" }}>
            <button className="btn btn-primary" type="submit" disabled={ctrlMutation.isPending}>
              {ctrlMutation.isPending ? "저장 중..." : "제어 기록 저장"}
            </button>
          </div>
        </form>

        {ctrlLogQ.data && ctrlLogQ.data.length > 0 ? (
          <>
            <div className="overflow-x">
              <table>
                <thead>
                  <tr style={{ textAlign: "left", color: "var(--color-text-muted)", fontSize: 19.5 }}>
                    <th>시각</th>
                    <th>제어 대상</th>
                    <th>조치</th>
                    <th>설정값</th>
                    <th>구역</th>
                    <th>이유</th>
                    <th>결과</th>
                    <th>센서(당시)</th>
                  </tr>
                </thead>
                <tbody>
                  {[...ctrlLogQ.data].reverse().map((r, i) => (
                    <tr key={i} style={{ borderTop: "1px solid var(--color-border)", fontSize: 20 }}>
                      <td style={{ padding: "6px 0" }}>{r["시각"]}</td>
                      <td>{r["제어 대상"]}</td>
                      <td>{r["조치"]}</td>
                      <td>{r["설정값"]}</td>
                      <td>{r["구역"]}</td>
                      <td>{r["이유"]}</td>
                      <td>{r["결과"]}</td>
                      <td>{r["센서(당시)"]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <a className="btn" style={{ marginTop: 10 }} href={controlApi.logExportUrl()}>
              제어 로그 엑셀 다운로드
            </a>
          </>
        ) : (
          <p style={{ fontSize: 20, color: "var(--color-text-muted)" }}>제어 기록이 없습니다. 위 폼으로 첫 번째 기록을 추가하세요.</p>
        )}
      </div>
    </div>
  );
}
