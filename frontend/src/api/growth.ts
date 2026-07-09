import { api } from "./client";
import type { GrowthRecord } from "../types/api";

export interface GrowthRecordIn {
  zone: string;
  crop_height_cm: number;
  leaf_count: number;
  fruit_count: number;
  truss_count: number;
  stem_diameter_mm: number;
  truss_height_cm?: number | null;
  notes?: string;
  record_date?: string | null;
}

export const growthApi = {
  list: (zone: string, days = 294) => api.get<GrowthRecord[]>("/growth", { zone, days }),
  latest: (zone: string) => api.get<GrowthRecord[]>("/growth/latest", { zone }),
  assessment: (zone: string, trend_days = 7, trend_tolerance = 3) =>
    api.get<Record<string, unknown>[]>("/growth/assessment", { zone, trend_days, trend_tolerance }),
  add: (record: GrowthRecordIn) => api.post<Record<string, unknown>>("/growth", record),
  exportUrl: (zone: string, days = 294) => api.fileUrl("/growth/export", { zone, days }),
};
