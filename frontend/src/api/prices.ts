import { api } from "./client";
import type {
  AllGrades,
  AuctionArchiveSummary,
  GradesByMarket,
  OriginMarketCycle,
  PriceBoard,
  PriceBriefingResult,
  PriceLedger,
  PriceMarketCompareRow,
  PriceToday,
  HarvestStrategy,
  SalesAdvice,
} from "../types/api";

export const pricesApi = {
  ledger: () => api.get<PriceLedger>("/prices/ledger"),
  grades: () => api.get<AllGrades>("/prices/grades"),
  gradesByMarket: () => api.get<GradesByMarket[]>("/prices/grades", { by_market: true }),
  today: () => api.get<PriceToday>("/prices/today"),
  board: (days: number, grade: string) => api.get<PriceBoard>("/prices/board", { days, grade }),
  compareMarkets: (days: number, grade: string) =>
    api.get<PriceMarketCompareRow[]>("/prices/compare-markets", { days, grade }),
  archiveLedger: () => api.post<AuctionArchiveSummary & { added: number; skipped: number; total_rows: number }>("/prices/archive-ledger"),
  archiveSummary: () => api.get<AuctionArchiveSummary>("/prices/archive-summary"),
  originMarketCycle: (days = 180, min_count = 3) =>
    api.get<OriginMarketCycle>("/prices/origin-market-cycle", { days, min_count }),
  harvestStrategy: (horizon_days = 14, grade = "중") =>
    api.get<HarvestStrategy>("/prices/harvest-strategy", { horizon_days, grade }),
  historyLong: (live = false) =>
    api.get<Record<string, unknown>[]>("/prices/history-long", { live }),
  briefing: (per_query_count = 5) =>
    api.post<{ job_id: string }>("/prices/briefing", { per_query_count }),
  salesAdvice: (current_price?: number, month?: number) =>
    api.post<SalesAdvice>("/prices/sales-advice", undefined, { current_price, month }),
};

export type { PriceBriefingResult };
