import { useState, type ReactElement, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  LabelList,
  Line,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { environmentApi } from "../api/environment";
import { weatherApi } from "../api/weather";
import { ErrorState, LoadingState } from "../components/common";
import { MetricCard, MetricGrid } from "../components/MetricCard";
import RiskCardPanel from "../components/RiskCardPanel";

const HOUR_OPTIONS = [6, 18, 24] as const;

function fmtTime(ts: string) {
  const d = new Date(ts);
  return `${String(d.getMonth() + 1).padStart(2, "0")}/${String(d.getDate()).padStart(2, "0")} ${String(
    d.getHours(),
  ).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function ChartCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="card">
      <h4 style={{ fontSize: 20, marginBottom: 10, color: "var(--color-text-muted)" }}>{title}</h4>
      <ResponsiveContainer width="100%" height={220}>
        {children as ReactElement}
      </ResponsiveContainer>
    </div>
  );
}

// ── 기상(외기·예보) 헬퍼 — 기상 탭에서 흡수 ──────────────────────────────
// 이슬점차(기온 - 이슬점, dew point depression)가 작을수록 상대습도가 100%에
// 가까워 표면(피복재·잎)이 조금만 더 식어도 결로가 생긴다 — 기본 습도물리
// 원리(특정 논문 인용 아님). 기온 자체가 "적정" 구간이어도 이슬점에 바짝
// 붙어 있으면 결로 위험이 있어 별도로 표시해야 한다(기존엔 기온만 보고
// "적정"이라 판정해 이 위험을 놓치고 있었음).
function tempLabel(t: number, dewpoint: number | null = null): [string, string] {
  const [baseLabel, baseColor] =
    t >= 35 ? ["고온 경보", "#e03131"] :
    t >= 30 ? ["고온 주의", "#f76707"] :
    t >= 20 ? ["적정", "#2f9e44"] :
    t >= 10 ? ["서늘", "#1971c2"] :
    ["저온 경보", "#6741d9"];

  if (dewpoint != null) {
    const spread = t - dewpoint;
    if (spread <= 2) return [`${baseLabel} · 결로 위험(이슬점차 ${spread.toFixed(1)}℃)`, "#e03131"];
    if (spread <= 4) return [`${baseLabel} · 결로 주의(이슬점차 ${spread.toFixed(1)}℃)`, "#f76707"];
  }
  return [baseLabel, baseColor];
}

// 온실이 남북 방향(용마루 남-북, 측창은 동·서쪽)으로 배치됐다는 가정 하의 판단.
// 측창을 통한 자연환기(압력차 환기)는 바람이 측벽에 수직으로 부딪힐 때(=동서풍) 가장
// 효과적이고, 용마루와 평행하게 흐르는 바람(=남북풍)은 측창 환기 효율이 떨어진다는
// 것은 건축환기 공기역학의 일반 원리다(특정 토마토 문헌이 아닌 일반 원리로 적용).
function _crossVentNote(dirDeg: number | null): string {
  if (dirDeg == null) return "";
  const d = ((dirDeg % 360) + 360) % 360;
  const distTo = (target: number) => Math.min(Math.abs(d - target), 360 - Math.abs(d - target));
  const isEW = distTo(90) <= 45 || distTo(270) <= 45; // 동풍 또는 서풍
  return isEW
    ? " · 남북 배치 온실 기준 측벽에 수직으로 부딪히는 방향이라 측창 자연환기 효율이 좋습니다"
    : " · 남북 배치 온실 기준 용마루와 평행한 방향이라 측창 자연환기 효율은 상대적으로 낮습니다(천창 위주로 고려)";
}

function windLabel(ws: number, dirKor: string, dirDeg: number | null = null): string {
  if (ws >= 10) return "강풍 — 천창 폐쇄 권장";
  if (ws >= 5) return "강한 바람 — 천창 개방 제한";
  if (ws >= 2) return `적정 바람 (${dirKor}방향) — 자연환기 가능${_crossVentNote(dirDeg)}`;
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

function renderPopLabel(props: { x?: unknown; y?: unknown; width?: unknown; height?: unknown; value?: unknown }) {
  const x = Number(props.x ?? 0);
  const y = Number(props.y ?? 0);
  const width = Number(props.width ?? 0);
  const height = Number(props.height ?? 0);
  const pop = Number(props.value);
  if (!Number.isFinite(pop) || pop <= 0 || height < 18) return <g />;
  return (
    <text x={x + width / 2} y={y + height - 6} textAnchor="middle" fill="#0b3d5c" fontSize={12} fontWeight={800}>
      {pop}%
    </text>
  );
}

export default function EnvironmentPage() {
  const qc = useQueryClient();
  const [hours, setHours] = useState<(typeof HOUR_OPTIONS)[number]>(24);

  const currentQ = useQuery({
    queryKey: ["env-current"],
    queryFn: environmentApi.current,
    refetchInterval: 60_000,
  });
  const riskQ = useQuery({ queryKey: ["env-risk"], queryFn: environmentApi.risk, refetchInterval: 60_000 });
  const historyQ = useQuery({
    queryKey: ["env-history", hours],
    queryFn: () => environmentApi.history(hours),
  });

  // 기상 탭 흡수분 — 외기 관측·환기 판단·단기예보
  const awsQ = useQuery({ queryKey: ["weather-aws"], queryFn: weatherApi.aws, refetchInterval: 60_000 });
  const forecastQ = useQuery({ queryKey: ["weather-forecast"], queryFn: weatherApi.forecast });
  const hintQ = useQuery({ queryKey: ["ventilation-hint"], queryFn: weatherApi.ventilationHint });
  const refreshMutation = useMutation({
    mutationFn: weatherApi.refresh,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["weather-aws"] });
      qc.invalidateQueries({ queryKey: ["ventilation-hint"] });
      qc.invalidateQueries({ queryKey: ["weather-forecast"] });
      qc.invalidateQueries({ queryKey: ["env-current"] });
    },
  });
  const aw = refreshMutation.data?.aws ?? awsQ.data;
  const warnings = refreshMutation.data?.warnings ?? [];

  if (currentQ.isLoading) return <LoadingState label="센서 데이터를 불러오는 중..." />;
  if (currentQ.isError) return <ErrorState message={(currentQ.error as Error).message} />;

  const sd = currentQ.data!;
  const chartData = (historyQ.data ?? []).map((r) => ({
    ...r,
    time: fmtTime(r.timestamp),
  }));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div>
          <span className={sd.source === "csv" ? "pill pill-good" : sd.source === "simulation" ? "pill pill-bad" : "pill"}>
            {sd.source === "csv" ? "온실 실측" : sd.source === "simulation" ? "시뮬레이션" : "수동"}
          </span>
          <span style={{ marginLeft: 8, fontSize: 19.5, color: "var(--color-text-muted)" }}>
            {sd.is_frozen && `최신 실측 고정 · ${sd.data_timestamp} · `}
            {sd.timestamp.slice(0, 19)}
          </span>
          {sd.solar_is_mock && (
            <span style={{ marginLeft: 8, fontSize: 19.5, color: "var(--color-warn)" }}>
              일사량은 목업값입니다 (CSV 로드 실패)
            </span>
          )}
        </div>
        <button className="btn btn-primary" onClick={() => refreshMutation.mutate()} disabled={refreshMutation.isPending}>
          {refreshMutation.isPending ? "기상 새로고침 중..." : "기상 새로고침"}
        </button>
      </div>

      {warnings.length > 0 && (
        <div className="card" style={{ borderColor: "var(--color-bad)" }}>
          {warnings.map((w, i) => (
            <p key={i} style={{ color: "var(--color-bad)", fontSize: 20 }}>{w}</p>
          ))}
          {refreshMutation.data?.alert_sent && (
            <p style={{ fontSize: 19.5, color: "var(--color-text-muted)" }}>이메일 경보가 발송되었습니다.</p>
          )}
        </div>
      )}

      <MetricGrid>
        <MetricCard label="온도" value={`${sd.temp}℃`} />
        <MetricCard label="습도" value={`${sd.rh}%`} />
        <MetricCard label="절대습도" value={`${sd.abs_humidity} g/m³`} />
        <MetricCard label="CO2" value={`${Math.round(sd.co2)} ppm`} />
        <MetricCard label="외부 일사" value={`${sd.solar} W/m²`} warn={sd.solar_is_mock} />
        <MetricCard label="VPD" value={`${sd.vpd} kPa`} />
      </MetricGrid>

      {riskQ.data && <RiskCardPanel risk={riskQ.data} />}

      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
          <h3 style={{ fontSize: 22 }}>온실 환경 패턴 (실측)</h3>
          <div style={{ display: "flex", gap: 6 }}>
            {HOUR_OPTIONS.map((h) => (
              <button
                key={h}
                className="btn"
                style={h === hours ? { background: "var(--color-primary)", color: "white", borderColor: "var(--color-primary)" } : undefined}
                onClick={() => setHours(h)}
              >
                {h}시간
              </button>
            ))}
          </div>
        </div>

        {historyQ.isLoading ? (
          <LoadingState />
        ) : chartData.length === 0 ? (
          <p style={{ fontSize: 20, color: "var(--color-text-muted)" }}>표시할 데이터가 없습니다.</p>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))", gap: 16 }}>
            <ChartCard title="온도(적색) & 습도(청색 점선)">
              <ComposedChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                <XAxis dataKey="time" tick={{ fontSize: 17 }} minTickGap={30} />
                <YAxis yAxisId="temp" tick={{ fontSize: 17 }} />
                <YAxis yAxisId="rh" orientation="right" tick={{ fontSize: 17 }} />
                <Tooltip />
                <Line yAxisId="temp" type="monotone" dataKey="temp" name="온도(℃)" stroke="#e03131" dot={false} strokeWidth={2} />
                <Line yAxisId="rh" type="monotone" dataKey="rh" name="습도(%)" stroke="#1971c2" dot={false} strokeWidth={2} strokeDasharray="5 3" />
              </ComposedChart>
            </ChartCard>

            <ChartCard title="CO2 — 주간 광합성 소비 · 야간 축적">
              <ComposedChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                <XAxis dataKey="time" tick={{ fontSize: 17 }} minTickGap={30} />
                <YAxis tick={{ fontSize: 17 }} />
                <Tooltip />
                <Line type="monotone" dataKey="co2" name="CO2(ppm)" stroke="#2f9e44" dot={false} strokeWidth={2} />
              </ComposedChart>
            </ChartCard>

            <ChartCard title="외부 일사(실측)">
              <ComposedChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                <XAxis dataKey="time" tick={{ fontSize: 17 }} minTickGap={30} />
                <YAxis tick={{ fontSize: 17 }} />
                <Tooltip />
                <Area type="monotone" dataKey="solar" name="일사량(W/m²)" stroke="#e67700" fill="#f59f00" fillOpacity={0.3} />
              </ComposedChart>
            </ChartCard>

            <ChartCard title="VPD — 녹색 = 적정 구간">
              <ComposedChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                <XAxis dataKey="time" tick={{ fontSize: 17 }} minTickGap={30} />
                <YAxis tick={{ fontSize: 17 }} domain={["auto", "auto"]} />
                <Tooltip />
                <ReferenceArea y1={0.3} y2={1.5} fill="#d3f9d8" fillOpacity={0.6} />
                <Line type="monotone" dataKey="vpd" name="VPD(kPa)" stroke="#862e9c" dot={false} strokeWidth={2} />
              </ComposedChart>
            </ChartCard>
          </div>
        )}
        <p style={{ fontSize: 19, color: "var(--color-text-muted)", marginTop: 10 }}>
          출처: 온실 실측 센서 로그 · 5분 간격 (최근 {hours}시간)
        </p>
      </div>

      {sd.cum_solar !== null && (
        <div className="card" style={{ fontSize: 20 }}>
          오늘 외부 누적 일사({sd.solar_is_mock ? "목업" : "실측"}): <strong>{Math.round(sd.cum_solar)} Wh/m²</strong>
          {" · "}현재 외부 {sd.solar} W/m² · 광량{" "}
          <strong>{sd.solar >= 400 ? "좋음" : sd.solar >= 150 ? "보통" : "부족"}</strong>
        </div>
      )}

      <div className="card">
        <h3 style={{ fontSize: 22, marginBottom: 14 }}>현재 상태 — 온실 내부 vs 외기</h3>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
          <div>
            <p style={{ fontSize: 19.5, color: "var(--color-text-muted)", marginBottom: 8 }}>온실 내부</p>
            <MetricGrid>
              <MetricCard label="온도" value={`${sd.temp}℃`} />
              <MetricCard label="상대습도" value={`${sd.rh}%`} />
              <MetricCard label="절대습도" value={`${sd.abs_humidity} g/m³`} />
              <MetricCard label="CO2" value={`${Math.round(sd.co2)} ppm`} />
              <MetricCard label="포화수분" value={`${sd.saturation_ah} g/m³`} hint="이 온도가 머금을 수 있는 최대 수분(RH 100%)" />
              <MetricCard label="수분부족" value={`${sd.moisture_deficit} g/m³`} hint="포화수분 − 현재 절대습도. 클수록 건조(증산 활발)" />
            </MetricGrid>
          </div>
          <div>
            <p style={{ fontSize: 19.5, color: "var(--color-text-muted)", marginBottom: 8 }}>온실 외부 (야외) · KMA AWS</p>
            {sd.outdoor ? (
              <MetricGrid>
                <MetricCard
                  label="야외 온도"
                  value={`${sd.outdoor.outdoor_temp}℃`}
                  delta={`실내외 ${(sd.temp - sd.outdoor.outdoor_temp).toFixed(1)}℃`}
                />
                <MetricCard label="야외 습도" value={`${sd.outdoor.outdoor_rh}%`} />
                <MetricCard label="야외 절대습도" value={`${sd.outdoor.abs_humidity} g/m³`} />
                <MetricCard label="야외 VPD" value={`${sd.outdoor.outdoor_vpd} kPa`} />
                <MetricCard label="풍속" value={`${sd.outdoor.wind_speed.toFixed(1)} m/s`} delta={`${sd.outdoor.wind_dir_kor} ${sd.outdoor.wind_dir_deg ?? "—"}°`} />
                <MetricCard label="야외 수분부족" value={`${sd.outdoor.moisture_deficit} g/m³`} />
              </MetricGrid>
            ) : (
              <p style={{ fontSize: 19.5, color: "var(--color-text-muted)" }}>야외 데이터 없음 (.env에 KMA_API_KEY 필요)</p>
            )}
          </div>
        </div>

        {aw && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 18 }}>
            <AnalysisCard title="외기 상태 분석">
              {(() => {
                const [label, color] = tempLabel(aw.temp, aw.dewpoint);
                return (
                  <>
                    <p style={{ marginBottom: 6, fontSize: 20 }}>
                      온도: <span style={{ color, fontWeight: 600 }}>{label}</span> ({aw.temp}℃) · 이슬점 {aw.dewpoint}℃ · 기압 {aw.pressure_hpa} hPa
                    </p>
                    <p style={{ marginBottom: 6, fontSize: 20 }}>바람: {windLabel(aw.wind_speed, aw.wind_dir_kor, aw.wind_dir_deg ?? null)}</p>
                    <p style={{ fontSize: 20 }}>강수: {aw.rainfall_60m > 0 ? `비 ${aw.rainfall_60m}mm/h — 천창 폐쇄 필수` : `강수 없음 (일강수 ${aw.rainfall_day}mm)`}</p>
                  </>
                );
              })()}
            </AnalysisCard>
            <AnalysisCard title="일사·환기 분석">
              <p style={{ fontSize: 20 }}>환기: {hintQ.data?.hint ?? "불러오는 중..."}</p>
            </AnalysisCard>
          </div>
        )}
      </div>

      <div className="card">
        <h3 style={{ fontSize: 22, marginBottom: 4 }}>앞으로 — 시간별 예보 (KMA 단기예보)</h3>
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
                <Line yAxisId="temp" type="monotone" dataKey="temp" name="외부온도(℃)" stroke="#e03131" strokeWidth={2} dot={false} />
                <Line yAxisId="rh" type="monotone" dataKey="rh" name="상대습도(%)" stroke="#1971c2" strokeWidth={2} dot={false} strokeDasharray="5 3" />
              </ComposedChart>
            </ResponsiveContainer>
            <p style={{ fontSize: 20, color: "var(--color-text-muted)", marginTop: 8 }}>
              빨강: 외부온도 · 파랑 점선: 상대습도 · 하늘색 막대: 강수확률. 광량은 아래 시간대별 아이콘으로 분리했습니다.
            </p>

            <div style={{ marginTop: 16 }}>
              <h4 style={{ fontSize: 20.5, marginBottom: 10, color: "var(--color-text-muted)" }}>예보광량 타임라인</h4>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(86px, 1fr))", gap: 8 }}>
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
                      <div style={{ fontSize: 19.5, color: "var(--color-text-muted)", marginBottom: 3 }}>{f.time.slice(0, 2)}시</div>
                      <div style={{ fontSize: 27.5, color: light.color, lineHeight: 1 }}>{light.icon}</div>
                      <div style={{ fontSize: 19.5, fontWeight: 800, color: light.color, marginTop: 4 }}>광량 {light.label}</div>
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
