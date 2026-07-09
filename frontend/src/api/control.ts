import { api } from "./client";
import type {
  AutoDiagnosisSettings,
  AutoDiagnosisStatus,
  ControlLogEntry,
  DiagnosisRecord,
  EmailAlertStatus,
} from "../types/api";

export interface ControlLogIn {
  target: string;
  action: string;
  setval?: string;
  zone?: string;
  reason?: string;
  result?: string;
}

export const controlApi = {
  diagnosisHistory: (n = 10) => api.get<DiagnosisRecord[]>("/control/diagnosis/history", { n }),
  submitDiagnosis: () => api.post<{ job_id: string }>("/control/diagnosis"),
  submitAdvice: () => api.post<{ job_id: string }>("/control/advice"),
  submitDiagnosisWithAdvice: () => api.post<{ job_id: string }>("/control/diagnosis-with-advice"),
  adviceResponse: (advice: Record<string, unknown>, response: string) =>
    api.post<{ ok: boolean }>("/control/advice/response", { advice, response }),
  adviceLog: (n = 20) => api.get<Record<string, unknown>[]>("/control/advice/log", { n }),

  getAutoSettings: () => api.get<AutoDiagnosisStatus>("/control/auto-diagnosis/settings"),
  putAutoSettings: (body: AutoDiagnosisSettings) =>
    api.put<AutoDiagnosisStatus>("/control/auto-diagnosis/settings", body),
  autoStatus: () => api.get<AutoDiagnosisStatus>("/control/auto-diagnosis/status"),

  emailStatus: () => api.get<EmailAlertStatus>("/control/email-alert/status"),
  emailTest: () => api.post<{ sent: boolean }>("/control/email-alert/test"),

  getLog: () => api.get<ControlLogEntry[]>("/control/log"),
  postLog: (body: ControlLogIn) => api.post<ControlLogEntry>("/control/log", body),
  logExportUrl: () => api.fileUrl("/control/log/export"),
};
