import { api } from "./client";
import type {
  VentilationHint,
  WeatherAws,
  WeatherDailySummary,
  WeatherForecastRow,
  WeatherRefreshResult,
} from "../types/api";

export const weatherApi = {
  aws: () => api.get<WeatherAws>("/weather/aws"),
  forecast: () => api.get<WeatherForecastRow[]>("/weather/forecast"),
  dailySummary: (days = 3) => api.get<WeatherDailySummary[]>("/weather/daily-summary", { days }),
  ventilationHint: () => api.get<VentilationHint>("/weather/ventilation-hint"),
  refresh: () => api.post<WeatherRefreshResult>("/weather/refresh"),
};
