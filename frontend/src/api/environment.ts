import { api } from "./client";
import type { EnvironmentCurrent, EnvironmentHistoryPoint, EnvironmentRisk } from "../types/api";

export const environmentApi = {
  current: () => api.get<EnvironmentCurrent>("/environment/current"),
  history: (hours: number) =>
    api.get<EnvironmentHistoryPoint[]>("/environment/history", { hours }),
  risk: () => api.get<EnvironmentRisk>("/environment/risk"),
};
