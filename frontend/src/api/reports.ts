import { api } from "./client";
import type { Report, ReportListItem, ReportSettings, ReportStatus } from "../types/api";

export const reportsApi = {
  getSettings: () => api.get<ReportSettings>("/reports/settings"),
  putSettings: (body: ReportSettings) => api.put<ReportSettings>("/reports/settings", body),
  status: () => api.get<ReportStatus>("/reports/status"),

  generate: (days = 7) => api.post<Report>("/reports/generate", { days }),
  list: () => api.get<ReportListItem[]>("/reports/list"),
  get: (reportId: string) => api.get<Report>(`/reports/${reportId}`),
  exportUrl: (reportId: string) => api.fileUrl(`/reports/${reportId}/export`),
};
