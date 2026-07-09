import { api } from "./client";
import type {
  AllGrades,
  AuctionArchiveSummary,
  DailyGradeHistory,
  DailyPriceByYear,
  DailyPriceHistory,
  GradesByMarket,
  MonthlySeasonalCycle,
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
  monthlySeasonalCycle: () =>
    api.get<MonthlySeasonalCycle>("/prices/monthly-seasonal-cycle"),
  dailyPriceHistory: (start: string, end: string, min_count = 1) =>
    api.get<DailyPriceHistory>("/prices/daily-price-history", { start, end, min_count }),
  dailyGradeHistory: (start: string, end: string) =>
    api.get<DailyGradeHistory>("/prices/daily-grade-history", { start, end }),
  dailyPriceByYear: (start: string, end: string, min_count = 1) =>
    api.get<DailyPriceByYear>("/prices/daily-price-by-year", { start, end, min_count }),
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
