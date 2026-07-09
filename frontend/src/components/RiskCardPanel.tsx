import { useState } from "react";
import { createPortal } from "react-dom";
import type { EnvironmentRisk, RiskCard } from "../types/api";
import { SeverityPill } from "./common";

const SEV_COLOR = { 0: "var(--color-good)", 1: "var(--color-warn)", 2: "var(--color-bad)" } as const;
const SEV_BG = { 0: "var(--color-good-bg)", 1: "var(--color-warn-bg)", 2: "var(--color-bad-bg)" } as const;

function CardRow({ card, onImageOpen }: { card: RiskCard; onImageOpen: (card: RiskCard) => void }) {
  const clickable = Boolean(card.thumb_url);

  return (
    <div
      style={{
        background: SEV_BG[card.severity],
        borderLeft: `4px solid ${SEV_COLOR[card.severity]}`,
        borderRadius: 8,
        padding: "10px 13px",
        marginBottom: 8,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 700, color: SEV_COLOR[card.severity] }}>
        {card.thumb_url && (
          <button
            type="button"
            onClick={() => onImageOpen(card)}
            title={`${card.title} 이미지 크게 보기`}
            style={{
              border: "none",
              background: "transparent",
              padding: 0,
              cursor: "zoom-in",
              lineHeight: 0,
            }}
          >
            <img src={card.thumb_url} alt="" style={{ width: 34, height: 34, objectFit: "cover", borderRadius: 6 }} />
          </button>
        )}
        <button
          type="button"
          onClick={() => clickable && onImageOpen(card)}
          disabled={!clickable}
          style={{
            border: "none",
            background: "transparent",
            padding: 0,
            color: "inherit",
            font: "inherit",
            fontWeight: 700,
            cursor: clickable ? "zoom-in" : "default",
            textAlign: "left",
            textDecoration: clickable ? "underline" : "none",
            textUnderlineOffset: 3,
          }}
          title={clickable ? `${card.title} 이미지 크게 보기` : undefined}
        >
          {card.title}
        </button>
        {card.pathogen_type && (
          <span
            className="pill"
            style={{
              background: "rgba(255, 255, 255, 0.7)",
              color: SEV_COLOR[card.severity],
              borderColor: SEV_COLOR[card.severity],
              fontSize: 17,
            }}
          >
            {card.pathogen_type}
          </span>
        )}
      </div>
      <div style={{ fontSize: 20, color: "var(--color-text)", lineHeight: 1.5, marginTop: 4 }}>{card.body}</div>
      {card.drugs.length > 0 && (
        <div style={{ fontSize: 19, color: "var(--color-primary)", marginTop: 4 }}>
          {card.drugs.join(" / ")}
        </div>
      )}
    </div>
  );
}

function ImageModal({ card, onClose }: { card: RiskCard; onClose: () => void }) {
  // Rendered via portal to document.body — .card's backdrop-filter otherwise
  // creates a new containing block, breaking position:fixed and making the
  // modal scroll with the page instead of staying pinned to the viewport.
  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`${card.title} 이미지`}
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        background: "rgba(15, 23, 42, 0.72)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 20,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "min(920px, 96vw)",
          maxHeight: "92vh",
          background: "var(--color-bg)",
          borderRadius: 16,
          boxShadow: "0 24px 80px rgba(0, 0, 0, 0.35)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
            padding: "14px 16px",
            borderBottom: "1px solid var(--color-border)",
          }}
        >
          <div>
            <h3 style={{ fontSize: 22, marginBottom: 3 }}>{card.title}</h3>
            <p style={{ fontSize: 19, color: "var(--color-text-muted)" }}>
              {card.pathogen_type ? `원인 분류: ${card.pathogen_type} · ` : ""}병 이름 또는 배경을 누르면 닫힙니다.
            </p>
          </div>
          <button className="btn" onClick={onClose}>
            닫기
          </button>
        </div>
        <div style={{ padding: 16, background: "var(--color-bg-soft)" }}>
          <img
            src={card.thumb_url}
            alt={card.title}
            style={{
              display: "block",
              width: "100%",
              maxHeight: "70vh",
              objectFit: "contain",
              borderRadius: 12,
              background: "#fff",
            }}
          />
        </div>
        <div style={{ padding: "12px 16px", fontSize: 20, lineHeight: 1.55 }}>
          <p>{card.body}</p>
          {card.drugs.length > 0 && (
            <p style={{ color: "var(--color-primary)", marginTop: 6 }}>추천 약제: {card.drugs.join(" / ")}</p>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

export default function RiskCardPanel({ risk }: { risk: EnvironmentRisk }) {
  const [expanded, setExpanded] = useState(false);
  const [showMore, setShowMore] = useState(false);
  const [showTable, setShowTable] = useState(false);
  const [imageCard, setImageCard] = useState<RiskCard | null>(null);

  const urgent = risk.cards.filter((c) => c.severity >= 1);
  const top = urgent.slice(0, 2);
  const rest = urgent.slice(2);

  return (
    <div className="card">
      <button
        onClick={() => setExpanded((v) => !v)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          width: "100%",
          background: "none",
          border: "none",
          padding: 0,
          textAlign: "left",
          font: "inherit",
        }}
      >
        <span style={{ fontWeight: 600, flex: 1 }}>현재 환경 위험도</span>
        <SeverityPill severity={risk.overall_severity} />
        <span style={{ color: "var(--color-text-muted)" }}>{expanded ? "접기" : "펼치기"}</span>
      </button>

      {expanded && (
        <div style={{ marginTop: 14 }}>
          {urgent.length === 0 ? (
            <p style={{ fontSize: 20, color: "var(--color-good)" }}>
              현재 주의가 필요한 환경·병해충 조건이 없습니다.
            </p>
          ) : (
            <>
              {top.map((c, i) => (
                <CardRow key={i} card={c} onImageOpen={setImageCard} />
              ))}
              {rest.length > 0 && (
                <>
                  <button className="btn" onClick={() => setShowMore((v) => !v)}>
                    {showMore ? "접기" : `더 보기 (${rest.length}건)`}
                  </button>
                  {showMore && (
                    <div style={{ marginTop: 8 }}>
                      {rest.map((c, i) => (
                        <CardRow key={i} card={c} onImageOpen={setImageCard} />
                      ))}
                    </div>
                  )}
                </>
              )}
            </>
          )}

          <div style={{ marginTop: 12 }}>
            <button className="btn" onClick={() => setShowTable((v) => !v)}>
              {showTable ? "병해충 위험도 표 접기" : "전체 병해충 위험도 표"}
            </button>
            {showTable && (
              <div className="overflow-x" style={{ marginTop: 10 }}>
                <table>
                  <thead>
                    <tr style={{ textAlign: "left", color: "var(--color-text-muted)", fontSize: 19.5 }}>
                      <th>병해충</th>
                      <th>구분</th>
                      <th>원인 분류</th>
                      <th>위험도</th>
                      <th>발생조건</th>
                    </tr>
                  </thead>
                  <tbody>
                    {risk.pest_table.map((r, i) => (
                      <tr key={i} style={{ borderTop: "1px solid var(--color-border)", fontSize: 20 }}>
                        <td style={{ padding: "6px 0" }}>{r.name}</td>
                        <td>{r.kind}</td>
                        <td>{r.pathogen_type || "—"}</td>
                        <td>{r.label}</td>
                        <td>{r.note}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <p style={{ fontSize: 19, color: "var(--color-text-muted)", marginTop: 12 }}>
            방제 기록은 영농일지 탭에 남겨주세요. 예) "A구역 잿빛곰팡이 방제 — 보스칼리드
            살포"처럼 적으면 자동 태그되고, 병해충 도감은 AI 상담 탭에서 조회할 수 있습니다.
          </p>
        </div>
      )}
      {imageCard && <ImageModal card={imageCard} onClose={() => setImageCard(null)} />}
    </div>
  );
}
