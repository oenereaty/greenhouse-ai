import { api } from "./client";
import type { NcpmsDetail, NcpmsSearchItem } from "../types/api";

export const chatApi = {
  diagnoseImage: (file: File, question: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("question", question);
    return api.postForm<{ job_id: string }>("/chat/diagnose-image", form);
  },
  ncpmsSearch: (crop = "토마토", rows = 100, start = 1) =>
    api.get<NcpmsSearchItem[]>("/chat/ncpms/search", { crop, rows, start }),
  ncpmsDetail: (sickKey: string) => api.get<NcpmsDetail>(`/chat/ncpms/${sickKey}`),
  sendMessage: (question: string) => api.post<{ job_id: string }>("/chat/message", { question }),
};
