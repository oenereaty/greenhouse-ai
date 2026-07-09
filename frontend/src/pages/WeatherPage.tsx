import type { ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CartesianGrid,
  ComposedChart,
  Line,
  Bar,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { weatherApi } from "../api/weather";
import { ErrorState, LoadingState } from "../components/common";
import { MetricCard, MetricGrid } from "../components/MetricCard";

function tempLabel(t: number): [string, string] {
  if (t >= 35) return ["고온 경보", "#e03131"];
  if (t >= 30) return ["고온 주의", "#f76707"];
  if (t >= 20) return ["적정", "#2f9e44"];
  if (t >= 10) return ["서늘", "#1971c2"];
  return ["저온 경보", "#6741d9"];
}

function windLabel(ws: number, dirKor: string): string {
  if (ws >= 10) return "강풍 — 천창 폐쇄 권장";
  if (ws >= 5) return "강한 바람 — 천창 개방 제한";
  if (ws >= 2) return `적정 바람 (${dirKor}방향) — 자연환기 가능`;
  return "무풍 — 자연환기 효율 낮음, 환풍기 고려";
}

function AnalysisCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={{ border: "1.5px solid var(--color-border)", borderRadius: 12, padding: "14px 16px", background: "var(--color-bg-soft)" }}>
      <div style={{ fontWeight: 700, marginBottom: 8 }}>{title}</div>
      {children}
    </div>
  );
}

function forecastTimeLabel(date: string, time: string) {
  return `${date.slice(4, 6)}/${date.slice(6, 8)} ${time.slice(0, 2)}시`;
}

function lightIcon(light: string) {
  if (light === "강") return { icon: "☀", label: "강", bg: "#fef3c7", color: "#b45309" };
  if (light === "중") return { icon: "◐", label: "중", bg: "#ecfdf5", color: "#047857" };
  if (light === "약") return { icon: "☁", label: "약", bg: "#f5f5f4", color: "#57534e" };
  return { icon: "—", label: "—", bg: "#fafaf9", color: "#78716c" };
}

function renderPopLabel(props: {
  x?: unknown;
  y?: unknown;
  width?: unknown;
  height?: unknown;
  value?: unknown;
}) {
  const x = Number(props.x ?? 0);
  const y = Number(props.y ?? 0);
  const width = Number(props.width ?? 0);
  const height = Number(props.height ?? 0);
  const value = props.value;
  const pop = Number(value);
  if (!Number.isFinite(pop) || pop <= 0 || height < 18) return <g />;
  return (
    <text
      x={x + width / 2}
      y={y + height - 6}
      textAnchor="middle"
      fill="#0b3d5c"
      fontSize={12}
      fontWeight={800}
    >
      {pop}%
    </text>
  );
}

export default function WeatherPage() {
  const qc = useQueryClient();
  const awsQ = useQuery({ queryKey: ["weather-aws"], queryFn: weatherApi.aws, refetchInterval: 60_000 });
  const forecastQ = useQuery({ queryKey: ["weather-forecast"], queryFn: weatherApi.forecast });
  const hintQ = useQuery({ queryKey: ["ventilation-hint"], queryFn: weatherApi.ventilationHint });

  const refreshMutation = useMutation({
    mutationFn: weatherApi.refresh,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["weather-aws"] });
      qc.invalidateQueries({ queryKey: ["ventilation-hint"] });
      qc.invalidateQueries({ queryKey: ["env-current"] });
    },
  });

  const aw = refreshMutation.data?.aws ?? awsQ.data;
  const warnings = refreshMutation.data?.warnings ?? [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <p style={{ fontSize: 20 }}>
          <strong>현재:</strong>{" "}
          {new Date().toLocaleString("ko-KR", { dateStyle: "long", timeStyle: "short" })} · 조회 기준: KMA AWS
        </p>
        <button className="btn btn-primary" onClick={() => refreshMutation.mutate()} disabled={refreshMutation.isPending}>
          {refreshMutation.isPending ? "새로고침 중..." : "기상 새로고침"}
        </button>
      </div>

      {warnings.length > 0 && (
        <div className="card" style={{ borderColor: "var(--color-bad)" }}>
          {warnings.map((w, i) => (
            <p key={i} style={{ color: "var(--color-bad)", fontSize: 20 }}>
              {w}
            </p>
          ))}
          {refreshMutation.data?.alert_sent && (
            <p style={{ fontSize: 19.5, color: "var(--color-text-muted)" }}>이메일 경보가 발송되었습니다.</p>
          )}
        </div>
      )}

      <div className="card">
        <h3 style={{ fontSize: 22, marginBottom: 4 }}>외부 현황 (KMA AWS 실시간 관측)</h3>
        {awsQ.isLoading ? (
          <LoadingState />
        ) : awsQ.isError ? (
          <ErrorState message={(awsQ.error as Error).message} />
        ) : aw ? (
          <>
            <p style={{ fontSize: 19.5, color: "var(--color-text-muted)", marginBottom: 12 }}>
              AWS 지점 {aw.stn} · 관측 시각: {aw.obs_time}
            </p>
            <MetricGrid>
              <MetricCard label="외기온도" value={`${aw.temp}℃`} />
              <MetricCard label="외기습도" value={`${aw.rh}%`} />
              <MetricCard label="VPD" value={`${aw.vpd} kPa`} />
              <MetricCard label="풍속" value={`${aw.wind_speed} m/s`} delta={`${aw.wind_dir_kor} ${aw.wind_dir_deg}°`} />
              <MetricCard label="이슬점" value={`${aw.dewpoint}℃`} />
              <MetricCard label="기압" value={`${aw.pressure_hpa} hPa`} />
              <MetricCard label="일강수량" value={`${aw.rainfall_day} mm`} />
              {aw.rainfall_60m > 0 && <MetricCard label="60분 강수" value={`${aw.rainfall_60m} mm`} warn />}
            </MetricGrid>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 18 }}>
              <AnalysisCard title="외기 상태 분석">
                {(() => {
                  const [label, color] = tempLabel(aw.temp);
                  return (
                    <>
                      <p style={{ marginBottom: 6, fontSize: 20 }}>
                        온도: <span style={{ color, fontWeight: 600 }}>{label}</span> ({aw.temp}℃)
                      </p>
                      <p style={{ marginBottom: 6, fontSize: 20 }}>바람: {windLabel(aw.wind_speed, aw.wind_dir_kor)}</p>
                      <p style={{ fontSize: 20 }}>강수: {aw.rainfall_60m > 0 ? `비 ${aw.rainfall_60m}mm/h — 천창 폐쇄 필수` : "강수 없음"}</p>
                    </>
                  );
                })()}
              </AnalysisCard>
              <AnalysisCard title="일사·환기 분석">
                <p style={{ fontSize: 20 }}>환기: {hintQ.data?.hint ?? "불러오는 중..."}</p>
              </AnalysisCard>
            </div>
          </>
        ) : (
          <p style={{ fontSize: 20, color: "var(--color-text-muted)" }}>.env에 KMA_API_KEY 설정 후 조회 가능</p>
        )}
      </div>

      <div className="card">
        <h3 style={{ fontSize: 22, marginBottom: 4 }}>시간별 예보 (KMA 단기예보)</h3>
        <p style={{ fontSize: 19.5, color: "var(--color-text-muted)", marginBottom: 12 }}>
          외부 온도·상대습도·하늘상태(운량)·강수확률 예보 · 예보광량은 하늘상태 기반 추정값
        </p>
        {forecastQ.isLoading ? (
          <LoadingState />
        ) : forecastQ.isError ? (
          <ErrorState message={(forecastQ.error as Error).message} />
        ) : (
          <>
            <ResponsiveContainer width="100%" height={320}>
              <ComposedChart
                data={(forecastQ.data ?? []).slice(0, 24).map((f) => ({
                  time: forecastTimeLabel(f.date, f.time),
                  temp: Number(f.TMP),
                  rh: Number(f.REH),
                  pop: Number(f.POP),
                  sky: f.sky_disp,
                  lightLabel: f.light_estimate,
                }))}
                margin={{ top: 12, right: 18, bottom: 48, left: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                <XAxis dataKey="time" tick={{ fontSize: 17 }} angle={-35} textAnchor="end" height={58} />
                <YAxis yAxisId="temp" tick={{ fontSize: 17 }} />
                <YAxis yAxisId="rh" orientation="right" tick={{ fontSize: 17 }} />
                <Tooltip
                  formatter={(value, name) => [value, name]}
                  labelFormatter={(label) => `${label} · ${(forecastQ.data ?? []).find((f) => forecastTimeLabel(f.date, f.time) === label)?.sky_disp ?? ""}`}
                />
                <Bar yAxisId="rh" dataKey="pop" name="강수확률(%)" fill="#74c0fc" fillOpacity={0.42}>
                  <LabelList dataKey="pop" content={renderPopLabel} />
                </Bar>
                <Line yAxisId="temp" type="natural" dataKey="temp" name="외부온도(℃)" stroke="#e03131" strokeWidth={2} dot={false} isAnimationActive animationDuration={1100} animationEasing="ease-out" />
                <Line yAxisId="rh" type="natural" dataKey="rh" name="상대습도(%)" stroke="#1971c2" strokeWidth={2} dot={false} strokeDasharray="5 3" isAnimationActive animationDuration={1100} animationEasing="ease-out" />
              </ComposedChart>
            </ResponsiveContainer>
            <p style={{ fontSize: 20, color: "var(--color-text-muted)", marginTop: 8 }}>
              빨강: 외부온도 · 파랑 점선: 상대습도 · 하늘색 막대: 강수확률. 광량은 아래 시간대별 아이콘으로 분리했습니다.
            </p>

            <div style={{ marginTop: 16 }}>
              <h4 style={{ fontSize: 20.5, marginBottom: 10, color: "var(--color-text-muted)" }}>예보광량 타임라인</h4>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(86px, 1fr))",
                  gap: 8,
                }}
              >
                {(forecastQ.data ?? []).slice(0, 24).map((f, i) => {
                  const light = lightIcon(f.light_estimate);
                  return (
                    <div
                      key={i}
                      title={`${forecastTimeLabel(f.date, f.time)} · ${f.sky_disp} · 광량 ${f.light_estimate}`}
                      style={{
                        border: "1px solid var(--color-border)",
                        borderRadius: 14,
                        background: light.bg,
                        padding: "9px 10px",
                        textAlign: "center",
                      }}
                    >
                      <div style={{ fontSize: 19.5, color: "var(--color-text-muted)", marginBottom: 3 }}>
                        {f.time.slice(0, 2)}시
                      </div>
                      <div style={{ fontSize: 27.5, color: light.color, lineHeight: 1 }}>{light.icon}</div>
                      <div style={{ fontSize: 19.5, fontWeight: 800, color: light.color, marginTop: 4 }}>
                        광량 {light.label}
                      </div>
                      <div style={{ fontSize: 18.5, color: "var(--color-text-muted)", marginTop: 2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                        {f.sky_disp}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
