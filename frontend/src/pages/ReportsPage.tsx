import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { reportsApi } from "../api/reports";
import { ErrorState, LoadingState } from "../components/common";
import { MetricCard, MetricGrid } from "../components/MetricCard";
import type { Report } from "../types/api";

function ReportDetail({ report }: { report: Report }) {
  const s = report.env.summary;
  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
        <h3 style={{ fontSize: 24 }}>
          {report.period.start} ~ {report.period.end} 리포트
        </h3>
        {report.report_id && (
          <a className="btn" href={reportsApi.exportUrl(report.report_id)}>
            엑셀 다운로드
          </a>
        )}
      </div>

      {report.env.coverage_note && (
        <p style={{ fontSize: 20, color: "var(--color-warn)", marginTop: 8 }}>⚠ {report.env.coverage_note}</p>
      )}

      {s ? (
        <div style={{ marginTop: 14 }}>
          <MetricGrid>
            <MetricCard label="평균 온도" value={`${s.avg_temp}℃`} />
            <MetricCard label="최고 온도" value={`${s.max_temp}℃`} />
            <MetricCard label="최저 온도" value={`${s.min_temp}℃`} />
            <MetricCard label="평균 습도" value={`${s.avg_rh}%`} />
            <MetricCard label="평균 CO2" value={`${s.avg_co2}ppm`} />
            <MetricCard label="데이터 있는 날" value={`${s.days_with_data}/${report.period.days}일`} />
          </MetricGrid>
        </div>
      ) : (
        <p style={{ fontSize: 20, color: "var(--color-text-muted)", marginTop: 12 }}>이 기간의 환경 데이터가 없습니다.</p>
      )}

      {report.env.daily.length > 0 && (
        <div style={{ marginTop: 20, height: 280 }}>
          <h4 style={{ fontSize: 22, marginBottom: 10 }}>일별 온도 추이</h4>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={report.env.daily}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" tick={{ fontSize: 15 }} />
              <YAxis tick={{ fontSize: 15 }} unit="℃" />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="avg_temp" name="평균온도" stroke="#3D7CF4" strokeWidth={2} />
              <Line type="monotone" dataKey="max_temp" name="최고온도" stroke="#e03131" strokeDasharray="4 3" />
              <Line type="monotone" dataKey="min_temp" name="최저온도" stroke="#1864ab" strokeDasharray="4 3" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {report.env.daily.length > 0 && (
        <div style={{ marginTop: 20, height: 280 }}>
          <h4 style={{ fontSize: 22, marginBottom: 10 }}>일별 습도·CO2 추이</h4>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={report.env.daily}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" tick={{ fontSize: 15 }} />
              <YAxis yAxisId="rh" tick={{ fontSize: 15 }} unit="%" />
              <YAxis yAxisId="co2" orientation="right" tick={{ fontSize: 15 }} unit="ppm" />
              <Tooltip />
              <Legend />
              <Line yAxisId="rh" type="monotone" dataKey="avg_rh" name="평균습도" stroke="#2f9e44" strokeWidth={2} />
              <Line yAxisId="co2" type="monotone" dataKey="avg_co2" name="평균CO2" stroke="#e67700" strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <div style={{ marginTop: 24 }}>
        <h4 style={{ fontSize: 22, marginBottom: 10 }}>농작업 기록 ({report.diary.length}건)</h4>
        {report.diary.length === 0 ? (
          <p style={{ fontSize: 20, color: "var(--color-text-muted)" }}>이 기간의 영농일지 기록이 없습니다.</p>
        ) : (
          report.diary.map((e, i) => (
            <div key={i} style={{ borderTop: "1px solid var(--color-border)", padding: "10px 0", fontSize: 20 }}>
              <strong>{e.date}</strong> {e.content}
              {e.tags.length > 0 && (
                <span style={{ color: "var(--color-text-muted)" }}> — {e.tags.join(", ")}</span>
              )}
            </div>
          ))
        )}
      </div>

      <div style={{ marginTop: 24 }}>
        <h4 style={{ fontSize: 22, marginBottom: 10 }}>병해 로그 ({report.disease_log.length}건)</h4>
        {report.disease_log.length === 0 ? (
          <p style={{ fontSize: 20, color: "var(--color-text-muted)" }}>이 기간의 병해·방제 기록이 없습니다.</p>
        ) : (
          report.disease_log.map((e, i) => (
            <div key={i} style={{ borderTop: "1px solid var(--color-border)", padding: "10px 0", fontSize: 20 }}>
              <strong>{e.date}</strong> {e.content}
              {e.pesticides.length > 0 && (
                <div style={{ color: "var(--color-text-muted)" }}>사용 약제: {e.pesticides.join(", ")}</div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export default function ReportsPage() {
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [genDays, setGenDays] = useState(7);
  const [intervalDays, setIntervalDays] = useState(7);

  const settingsQ = useQuery({ queryKey: ["report-settings"], queryFn: reportsApi.getSettings });
  const listQ = useQuery({ queryKey: ["report-list"], queryFn: reportsApi.list });
  const detailQ = useQuery({
    queryKey: ["report-detail", selectedId],
    queryFn: () => reportsApi.get(selectedId!),
    enabled: !!selectedId,
  });

  const settingsMutation = useMutation({
    mutationFn: (enabled: boolean) => reportsApi.putSettings({ enabled, interval_days: intervalDays }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["report-settings"] }),
  });

  const generateMutation = useMutation({
    mutationFn: () => reportsApi.generate(genDays),
    onSuccess: (report) => {
      qc.invalidateQueries({ queryKey: ["report-list"] });
      setSelectedId(report.report_id ?? null);
    },
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div className="card">
        <h3 style={{ fontSize: 24, marginBottom: 6 }}>리포트</h3>
        <p style={{ fontSize: 20.5, color: "var(--color-text-muted)", marginBottom: 14 }}>
          온실 환경데이터 통계·시각화, 농작업 기록, 병해 로그를 지정한 주기마다 자동으로 생성합니다.
        </p>

        <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 20 }}>
            <input
              type="checkbox"
              checked={settingsQ.data?.enabled ?? false}
              onChange={(e) => settingsMutation.mutate(e.target.checked)}
            />
            자동 생성 켜기
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 20 }}>
            주기(일)
            <input
              type="number"
              min={1}
              value={intervalDays}
              onChange={(e) => {
                const v = Math.max(1, Number(e.target.value) || 7);
                setIntervalDays(v);
                if (settingsQ.data?.enabled) reportsApi.putSettings({ enabled: true, interval_days: v }).then(() => qc.invalidateQueries({ queryKey: ["report-settings"] }));
              }}
              style={{ width: 60, padding: 6, borderRadius: 6, border: "1px solid var(--color-border)" }}
            />
          </label>
          <span style={{ fontSize: 19.5, color: "var(--color-text-muted)" }}>기본값 7일</span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 16, flexWrap: "wrap" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 20 }}>
            지금 생성 — 최근
            <input
              type="number"
              min={1}
              value={genDays}
              onChange={(e) => setGenDays(Math.max(1, Number(e.target.value) || 7))}
              style={{ width: 60, padding: 6, borderRadius: 6, border: "1px solid var(--color-border)" }}
            />
            일
          </label>
          <button className="btn btn-primary" disabled={generateMutation.isPending} onClick={() => generateMutation.mutate()}>
            {generateMutation.isPending ? "생성 중..." : "리포트 생성"}
          </button>
        </div>
      </div>

      <div className="card">
        <h4 style={{ fontSize: 22, marginBottom: 10 }}>생성된 리포트</h4>
        {listQ.isLoading && <LoadingState />}
        {listQ.isError && <ErrorState message="리포트 목록을 불러오지 못했습니다." />}
        {listQ.data && listQ.data.length === 0 && (
          <p style={{ fontSize: 20, color: "var(--color-text-muted)" }}>아직 생성된 리포트가 없습니다. 위에서 생성해 보세요.</p>
        )}
        {listQ.data && listQ.data.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {listQ.data.map((r) => (
              <button
                key={r.report_id}
                className="btn"
                style={{
                  justifyContent: "flex-start",
                  textAlign: "left",
                  background: selectedId === r.report_id ? "var(--color-good-bg)" : undefined,
                }}
                onClick={() => setSelectedId(r.report_id)}
              >
                {r.period.start} ~ {r.period.end} · 농작업 {r.diary_count}건 · 병해 {r.disease_count}건
              </button>
            ))}
          </div>
        )}
      </div>

      {selectedId && detailQ.isLoading && <LoadingState label="리포트 불러오는 중..." />}
      {selectedId && detailQ.isError && <ErrorState message="리포트를 불러오지 못했습니다." />}
      {detailQ.data && <ReportDetail report={detailQ.data} />}
    </div>
  );
}
