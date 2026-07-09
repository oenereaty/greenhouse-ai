import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend } from "recharts";
import { growthApi, type GrowthRecordIn } from "../api/growth";
import { ErrorState, LoadingState } from "../components/common";
import { MetricCard, MetricGrid } from "../components/MetricCard";

const ZONE_COLORS: Record<string, string> = {
  A: "#3D7CF4", B: "#2f9e44", C: "#e67700", D: "#862e9c", "전체": "#495057",
};

// 같은 온실 구역이라 값이 서로 비슷해 색만으로 구분이 어려울 때가 있어(사용자
// 피드백), 선 모양도 구역별로 다르게 줘서 겹쳐도 구분되게 한다.
const ZONE_DASH: Record<string, string> = { A: "0", B: "6 3", C: "2 3", D: "8 3 2 3" };

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
            {["전체", "A", "B", "C", "D"].map((z) => (
              <option key={z} value={z}>
                {z}
              </option>
            ))}
          </select>
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 19.5, minWidth: 140 }}>
          최근 {weeks}주
          <input type="range" min={1} max={42} value={weeks} onChange={(e) => setWeeks(Number(e.target.value))} style={{ width: 140 }} />
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

      {assessQ.data && assessQ.data.length > 0 && (
        <div className="card">
          <p style={{ fontSize: 19.5, color: "var(--color-text-muted)", marginBottom: 10 }}>
            핵심 생육 지표 — 초장·줄기두께는 전 주 대비 추세, 화방높이는 균형 추정(아래 상세 설명 참고)
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 14 }}>
            {assessQ.data.map((a, i) => (
              <div
                key={i}
                style={{
                  border: "1px solid var(--color-border)",
                  borderRadius: 10,
                  padding: "12px 14px",
                  background: "var(--color-bg-soft)",
                }}
              >
                <div style={{ fontSize: 21, fontWeight: 700, marginBottom: 8 }}>
                  구역 {String(a.zone)} <span style={{ fontWeight: 400, color: "var(--color-text-muted)", fontSize: 18 }}>({String(a.date)})</span>
                </div>

                <div style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: 19, fontWeight: 600 }}>
                    화방높이{a.truss_status ? <>: {String(a.truss_status)}</> : null}
                  </div>
                  <div style={{ fontSize: 18, color: "var(--color-text-muted)", lineHeight: 1.55, marginTop: 2 }}>
                    {String(a.truss_desc)}
                  </div>
                </div>

                <div style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: 19, fontWeight: 600 }}>초장 추세</div>
                  <div style={{ fontSize: 18, color: "var(--color-text-muted)", lineHeight: 1.55, marginTop: 2 }}>
                    {String(a.crop_height_cm_trend_desc)}
                  </div>
                </div>

                <div>
                  <div style={{ fontSize: 19, fontWeight: 600 }}>줄기두께 추세</div>
                  <div style={{ fontSize: 18, color: "var(--color-text-muted)", lineHeight: 1.55, marginTop: 2 }}>
                    {String(a.stem_diameter_mm_trend_desc)}
                  </div>
                </div>
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
            <p style={{ fontSize: 18, color: "var(--color-text-muted)", marginBottom: 8 }}>
              Y축은 0이 아니라 구역별 실제 값 범위에 맞춰 확대했습니다 — 구역 간 초장 차이는 몇 cm 수준으로 작아 0부터 그리면 거의 겹쳐 보입니다.
            </p>
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={heightSeries}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                <XAxis dataKey="date" tick={{ fontSize: 17 }} />
                <YAxis tick={{ fontSize: 17 }} domain={["auto", "auto"]} />
                <Tooltip />
                <Legend />
                {zones.map((z) => (
                  <Line
                    key={z} type="monotone" dataKey={z} name={`구역 ${z}`}
                    stroke={ZONE_COLORS[z] ?? "#333"} strokeWidth={2.5}
                    strokeDasharray={ZONE_DASH[z]} dot={{ r: 3 }}
                    isAnimationActive animationDuration={1100} animationEasing="ease-out"
                  />
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
                    <Line
                      key={z} type="monotone" dataKey={z} name={`구역 ${z}`}
                      stroke={ZONE_COLORS[z] ?? "#333"} strokeWidth={2.5}
                      strokeDasharray={ZONE_DASH[z]} dot={{ r: 3 }}
                    />
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
                    <Line
                      key={z} type="monotone" dataKey={z} name={`구역 ${z}`}
                      stroke={ZONE_COLORS[z] ?? "#333"} strokeWidth={2.5}
                      strokeDasharray={ZONE_DASH[z]} dot={false}
                      isAnimationActive animationDuration={1100} animationEasing="ease-out"
                    />
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
              {["A", "B", "C", "D"].map((z) => (
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
