import { api } from "./client";
import type { SystemConfig, SystemHealth } from "../types/api";

export const systemApi = {
  health: () => api.get<SystemHealth>("/system/health"),
  config: () => api.get<SystemConfig>("/system/config"),
};
