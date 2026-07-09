import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend } from "recharts";
import { growthApi, type GrowthRecordIn } from "../api/growth";
import { pricesApi } from "../api/prices";
import { ErrorState, LoadingState } from "../components/common";
import { MetricCard, MetricGrid } from "../components/MetricCard";

const ZONE_COLORS: Record<string, string> = { A: "#3D7CF4", B: "#2f9e44", C: "#e67700", "전체": "#495057" };

function pivotByZoneDate(records: { date: string; zone: string; [k: string]: unknown }[], field: string) {
  const byDate = new Map<string, Record<string, number | string>>();
  for (const r of records) {
    const v = Number(r[field]);
    if (Number.isNaN(v)) continue;
    if (!byDate.has(r.date)) byDate.set(r.date, { date: r.date });
    const row = byDate.get(r.date)!;
    row[r.zone] = v;
  }
  return Array.from(byDate.values()).sort((a, b) => String(a.date).localeCompare(String(b.date)));
}

function flagOutliers(records: { date: string; zone: string; crop_height_cm: string }[]) {
  const byZone = new Map<string, typeof records>();
  for (const r of records) {
    if (!byZone.has(r.zone)) byZone.set(r.zone, []);
    byZone.get(r.zone)!.push(r);
  }
  const outliers: { zone: string; date: string; deltaCm: number; cpw: number }[] = [];
  for (const [zone, rows] of byZone) {
    const sorted = [...rows].sort((a, b) => a.date.localeCompare(b.date));
    for (let i = 1; i < sorted.length; i++) {
      const prev = Number(sorted[i - 1].crop_height_cm);
      const cur = Number(sorted[i].crop_height_cm);
      if (Number.isNaN(prev) || Number.isNaN(cur)) continue;
      const deltaDays = Math.max(
        1,
        (new Date(sorted[i].date).getTime() - new Date(sorted[i - 1].date).getTime()) / 86400000,
      );
      const deltaCm = cur - prev;
      const cpw = Math.round(((deltaCm / deltaDays) * 7) * 10) / 10;
      if (deltaCm < -5 || cpw > 50) {
        outliers.push({ zone, date: sorted[i].date, deltaCm, cpw });
      }
    }
  }
  return outliers;
}

const emptyForm: GrowthRecordIn = {
  zone: "A",
  crop_height_cm: 50,
  leaf_count: 15,
  fruit_count: 5,
  truss_count: 3,
  stem_diameter_mm: 9,
  truss_height_cm: 12,
  notes: "",
};

export default function GrowthPage() {
  const [zone, setZone] = useState("전체");
  const [weeks, setWeeks] = useState(42);
  const [form, setForm] = useState<GrowthRecordIn>(emptyForm);
  const [visibleRecordCount, setVisibleRecordCount] = useState(5);
  const qc = useQueryClient();
  const days = weeks * 7;

  const recordsQ = useQuery({ queryKey: ["growth", zone, days], queryFn: () => growthApi.list(zone, days) });
  const latestQ = useQuery({ queryKey: ["growth-latest", zone], queryFn: () => growthApi.latest(zone) });
  const assessQ = useQuery({ queryKey: ["growth-assessment", zone], queryFn: () => growthApi.assessment(zone) });
  const strategyQ = useQuery({ queryKey: ["harvest-strategy", 14], queryFn: () => pricesApi.harvestStrategy(14, "중") });

  const addMutation = useMutation({
    mutationFn: (r: GrowthRecordIn) => growthApi.add(r),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["growth"] });
      qc.invalidateQueries({ queryKey: ["growth-latest"] });
      qc.invalidateQueries({ queryKey: ["growth-assessment"] });
      setForm(emptyForm);
    },
  });

  const outliers = useMemo(() => flagOutliers(recordsQ.data ?? []), [recordsQ.data]);
  const outlierKeySet = useMemo(
    () => new Set(outliers.map((o) => `${o.zone}|${o.date}`)),
    [outliers],
  );
  const cleanRecords = useMemo(
    () => (recordsQ.data ?? []).filter((r) => !outlierKeySet.has(`${r.zone}|${r.date}`)),
    [recordsQ.data, outlierKeySet],
  );

  const heightSeries = useMemo(() => pivotByZoneDate(cleanRecords, "crop_height_cm"), [cleanRecords]);
  const trussHeightSeries = useMemo(() => pivotByZoneDate(recordsQ.data ?? [], "truss_height_cm"), [recordsQ.data]);
  const stemSeries = useMemo(() => pivotByZoneDate(recordsQ.data ?? [], "stem_diameter_mm"), [recordsQ.data]);
  const zones = useMemo(() => Array.from(new Set(cleanRecords.map((r) => r.zone))), [cleanRecords]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div className="card" style={{ display: "flex", gap: 20, alignItems: "flex-end", flexWrap: "wrap" }}>
        <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 19.5 }}>
          구역
          <select value={zone} onChange={(e) => setZone(e.target.value)} style={{ padding: 6, borderRadius: 6, border: "1px solid var(--color-border)" }}>
            {["전체", "A", "B", "C"].map((z) => (
              <option key={z} value={z}>
                {z}
              </option>
            ))}
          </select>
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 19.5, flex: 1, minWidth: 220 }}>
          최근 {weeks}주
          <input type="range" min={1} max={42} value={weeks} onChange={(e) => setWeeks(Number(e.target.value))} />
        </label>
      </div>

      {latestQ.data && latestQ.data.length > 0 && (
        <div className="card">
          <p style={{ fontSize: 19.5, color: "var(--color-text-muted)", marginBottom: 10 }}>최신 생육 현황</p>
          <MetricGrid>
            {latestQ.data.map((rec) => (
              <MetricCard
                key={rec.zone}
                label={`구역 ${rec.zone} 초장`}
                value={`${rec.crop_height_cm} cm`}
                delta={`엽수 ${rec.leaf_count} · 착과 ${rec.fruit_count} · 화방 ${rec.truss_count} · 줄기 ${rec.stem_diameter_mm}mm`}
                hint={`${rec.date} | ${rec.notes}`}
              />
            ))}
          </MetricGrid>
        </div>
      )}

      <div className="card" style={{ border: "1.5px solid rgba(47, 158, 68, 0.35)" }}>
        <h3 style={{ fontSize: 24, marginBottom: 6 }}>시장 연계 출하·온도 전략</h3>
        <p style={{ fontSize: 20.5, color: "var(--color-text-muted)", marginBottom: 14 }}>
          착과 상태와 최근 경락가 흐름을 묶어 2주 뒤 출하 타이밍에 맞춘 온도 관리 방향을 제안합니다.
        </p>
        {strategyQ.isLoading ? (
          <LoadingState />
        ) : strategyQ.isError ? (
          <ErrorState message={(strategyQ.error as Error).message} />
        ) : strategyQ.data ? (
          <div style={{ display: "grid", gridTemplateColumns: "minmax(260px, 0.9fr) minmax(280px, 1.1fr)", gap: 18 }}>
            <div
              style={{
                padding: 18,
                borderRadius: 18,
                background: "linear-gradient(135deg, rgba(231, 245, 255, 0.95), rgba(235, 251, 238, 0.95))",
                border: "1px solid var(--color-border)",
              }}
            >
              <div style={{ fontSize: 19.5, color: "var(--color-text-muted)", fontWeight: 800, marginBottom: 8 }}>
                {strategyQ.data.target_date} 기준
              </div>
              <div style={{ fontSize: 32, fontWeight: 900, color: "var(--color-primary-strong)", marginBottom: 10 }}>
                {strategyQ.data.action}
              </div>
              <p style={{ fontSize: 22, lineHeight: 1.75, margin: 0 }}>{strategyQ.data.temperature_strategy}</p>
            </div>
            <div style={{ display: "grid", gap: 10, fontSize: 22, lineHeight: 1.7 }}>
              <div>
                <strong>판단 근거</strong>
                <div>{strategyQ.data.rationale}</div>
              </div>
              <div>
                <strong>가격 신호</strong>
                <div>
                  현재 {strategyQ.data.price.current_price?.toLocaleString() ?? "?"}원 → 2주 후 추정{" "}
                  {strategyQ.data.price.projected_price?.toLocaleString() ?? "?"}원
                  {strategyQ.data.price.change_pct !== null ? ` (${strategyQ.data.price.change_pct > 0 ? "+" : ""}${strategyQ.data.price.change_pct}%)` : ""}
                </div>
                <div style={{ color: "var(--color-text-muted)" }}>{strategyQ.data.price.reason}</div>
              </div>
              <div>
                <strong>생육 신호</strong>
                <div>
                  초장 추세 {strategyQ.data.growth.avg_height_trend_cm != null ? `${strategyQ.data.growth.avg_height_trend_cm > 0 ? "+" : ""}${strategyQ.data.growth.avg_height_trend_cm}cm` : "—"}
                  {" · "}줄기굵기 추세 {strategyQ.data.growth.avg_stem_trend_mm != null ? `${strategyQ.data.growth.avg_stem_trend_mm > 0 ? "+" : ""}${strategyQ.data.growth.avg_stem_trend_mm}mm` : "—"}
                  {" · "}화방높이 균형 영양{strategyQ.data.growth.truss_balance?.["영양생장쪽"] ?? 0}/생식{strategyQ.data.growth.truss_balance?.["생식생장쪽"] ?? 0}/균형{strategyQ.data.growth.truss_balance?.["균형"] ?? 0}
                </div>
                <div style={{ color: "var(--color-text-muted)" }}>{strategyQ.data.growth.reason}</div>
              </div>
              <div>
                <strong>환경 제약</strong>
                <div>
                  온도 {strategyQ.data.climate.temp}℃ · 습도 {strategyQ.data.climate.rh}% — {strategyQ.data.climate.reason}
                </div>
              </div>
              <div style={{ fontSize: 20, color: "var(--color-text-muted)" }}>
                {strategyQ.data.caveats.join(" ")}
              </div>
            </div>
          </div>
        ) : null}
      </div>

      {assessQ.data && assessQ.data.length > 0 && (
        <div className="card">
          <p style={{ fontSize: 19.5, color: "var(--color-text-muted)", marginBottom: 10 }}>
            핵심 생육 지표 — 초장·줄기두께는 전 주 대비 추세, 화방높이는 균형 추정(아래 상세 설명 참고)
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 16 }}>
            {assessQ.data.map((a, i) => (
              <div key={i} style={{ fontSize: 20, lineHeight: 1.7 }}>
                <strong>구역 {String(a.zone)}</strong> ({String(a.date)})
                {a.truss_status ? (
                  <div>
                    화방높이: <strong>{String(a.truss_status)}</strong>
                    <div style={{ color: "var(--color-text-muted)" }}>{String(a.truss_desc)}</div>
                  </div>
                ) : (
                  <div style={{ color: "var(--color-text-muted)" }}>{String(a.truss_desc)}</div>
                )}
                <div style={{ color: "var(--color-text-muted)" }}>{String(a.crop_height_cm_trend_desc)}</div>
                <div style={{ color: "var(--color-text-muted)" }}>{String(a.stem_diameter_mm_trend_desc)}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {recordsQ.isLoading && <LoadingState />}
      {recordsQ.isError && <ErrorState message={(recordsQ.error as Error).message} />}

      {outliers.length > 0 && (
        <div className="card" style={{ borderColor: "var(--color-warn)" }}>
          {outliers.map((o, i) => (
            <p key={i} style={{ fontSize: 19.5, color: "var(--color-warn)" }}>
              이상치 제외 — 구역 {o.zone} · {o.date} · 전 측정 대비 {o.deltaCm.toFixed(1)}cm (주간 환산 {o.cpw.toFixed(1)} cm/주)
            </p>
          ))}
        </div>
      )}

      {recordsQ.data && recordsQ.data.length > 0 ? (
        <>
          <div className="card">
            <h3 style={{ fontSize: 24, marginBottom: 12 }}>초장 추이</h3>
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={heightSeries}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                <XAxis dataKey="date" tick={{ fontSize: 17 }} />
                <YAxis tick={{ fontSize: 17 }} domain={[0, "auto"]} />
                <Tooltip />
                <Legend />
                {zones.map((z) => (
                  <Line key={z} type="monotone" dataKey={z} name={`구역 ${z}`} stroke={ZONE_COLORS[z] ?? "#333"} dot />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))", gap: 16 }}>
            <div className="card">
              <h4 style={{ fontSize: 22, marginBottom: 10 }}>화방높이 추이</h4>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={trussHeightSeries}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="date" tick={{ fontSize: 17 }} />
                  <YAxis tick={{ fontSize: 17 }} domain={[0, "auto"]} />
                  <Tooltip />
                  <Legend />
                  {zones.map((z) => (
                    <Line key={z} type="monotone" dataKey={z} name={`구역 ${z}`} stroke={ZONE_COLORS[z] ?? "#333"} dot />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="card">
              <h4 style={{ fontSize: 22, marginBottom: 10 }}>줄기직경 추이</h4>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={stemSeries}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="date" tick={{ fontSize: 17 }} />
                  <YAxis tick={{ fontSize: 17 }} domain={[0, "auto"]} />
                  <Tooltip />
                  <Legend />
                  {zones.map((z) => (
                    <Line key={z} type="monotone" dataKey={z} name={`구역 ${z}`} stroke={ZONE_COLORS[z] ?? "#333"} dot={false} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
              <h3 style={{ fontSize: 24 }}>전체 데이터</h3>
              <a className="btn" href={growthApi.exportUrl(zone, days)}>
                엑셀로 내보내기
              </a>
            </div>
            <div className="overflow-x">
              <table>
                <thead>
                  <tr style={{ textAlign: "left", color: "var(--color-text-muted)", fontSize: 19.5 }}>
                    <th>날짜</th>
                    <th>구역</th>
                    <th>초장(cm)</th>
                    <th>엽수</th>
                    <th>착과수</th>
                    <th>화방수</th>
                    <th>줄기직경(mm)</th>
                    <th>화방높이(cm)</th>
                    <th>비고</th>
                  </tr>
                </thead>
                <tbody>
                  {recordsQ.data.slice(0, visibleRecordCount).map((r, i) => (
                    <tr key={i} style={{ borderTop: "1px solid var(--color-border)", fontSize: 20 }}>
                      <td style={{ padding: "6px 0" }}>{r.date}</td>
                      <td>{r.zone}</td>
                      <td>{r.crop_height_cm}</td>
                      <td>{r.leaf_count}</td>
                      <td>{r.fruit_count}</td>
                      <td>{r.truss_count}</td>
                      <td>{r.stem_diameter_mm}</td>
                      <td>{r.truss_height_cm}</td>
                      <td>{r.notes}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {recordsQ.data.length > visibleRecordCount && (
              <button
                className="btn"
                style={{ marginTop: 10 }}
                onClick={() => setVisibleRecordCount((n) => Math.min(recordsQ.data.length, n + 20))}
              >
                더보기 ({Math.min(visibleRecordCount, recordsQ.data.length)}/{recordsQ.data.length})
              </button>
            )}
            {visibleRecordCount > 5 && (
              <button className="btn" style={{ marginTop: 10, marginLeft: 8 }} onClick={() => setVisibleRecordCount(5)}>
                접기
              </button>
            )}
          </div>
        </>
      ) : (
        !recordsQ.isLoading && <p style={{ fontSize: 20, color: "var(--color-text-muted)" }}>해당 조건의 생육 데이터가 없습니다.</p>
      )}

      <div className="card">
        <h3 style={{ fontSize: 24, marginBottom: 14 }}>생육 측정값 입력</h3>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            addMutation.mutate(form);
          }}
          style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 14 }}
        >
          <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 19.5 }}>
            구역
            <select value={form.zone} onChange={(e) => setForm({ ...form, zone: e.target.value })} style={{ padding: 6, borderRadius: 6, border: "1px solid var(--color-border)" }}>
              {["A", "B", "C"].map((z) => (
                <option key={z} value={z}>
                  {z}
                </option>
              ))}
            </select>
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 19.5 }}>
            초장 (cm)
            <input type="number" step={0.1} value={form.crop_height_cm} onChange={(e) => setForm({ ...form, crop_height_cm: Number(e.target.value) })} style={{ padding: 6, borderRadius: 6, border: "1px solid var(--color-border)" }} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 19.5 }}>
            엽수
            <input type="number" value={form.leaf_count} onChange={(e) => setForm({ ...form, leaf_count: Number(e.target.value) })} style={{ padding: 6, borderRadius: 6, border: "1px solid var(--color-border)" }} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 19.5 }}>
            착과수
            <input type="number" value={form.fruit_count} onChange={(e) => setForm({ ...form, fruit_count: Number(e.target.value) })} style={{ padding: 6, borderRadius: 6, border: "1px solid var(--color-border)" }} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 19.5 }}>
            화방수
            <input type="number" value={form.truss_count} onChange={(e) => setForm({ ...form, truss_count: Number(e.target.value) })} style={{ padding: 6, borderRadius: 6, border: "1px solid var(--color-border)" }} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 19.5 }}>
            줄기직경 (mm)
            <input type="number" step={0.1} value={form.stem_diameter_mm} onChange={(e) => setForm({ ...form, stem_diameter_mm: Number(e.target.value) })} style={{ padding: 6, borderRadius: 6, border: "1px solid var(--color-border)" }} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 19.5 }}>
            화방높이 (cm)
            <input type="number" step={0.5} value={form.truss_height_cm ?? 0} onChange={(e) => setForm({ ...form, truss_height_cm: Number(e.target.value) })} style={{ padding: 6, borderRadius: 6, border: "1px solid var(--color-border)" }} />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 19.5, gridColumn: "1 / -1" }}>
            비고
            <input type="text" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} style={{ padding: 6, borderRadius: 6, border: "1px solid var(--color-border)" }} />
          </label>
          <div style={{ gridColumn: "1 / -1" }}>
            <button className="btn btn-primary" type="submit" disabled={addMutation.isPending}>
              {addMutation.isPending ? "저장 중..." : "기록 저장"}
            </button>
            {addMutation.isSuccess && <span style={{ marginLeft: 10, color: "var(--color-good)", fontSize: 19.5 }}>저장 완료</span>}
          </div>
        </form>
      </div>
    </div>
  );
}
