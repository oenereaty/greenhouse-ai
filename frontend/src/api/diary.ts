import { api } from "./client";
import type {
  DetectTagsResult,
  DiaryEntry,
  HarvestStatus,
  NutrientEntry,
  NutrientRecipe,
  UpcomingPlan,
} from "../types/api";

export interface DiaryEntryIn {
  date: string;
  content: string;
  tags?: string[];
  pesticides?: string[];
  attachments?: { stored_name: string; original_name: string }[];
}

export const diaryApi = {
  all: () => api.get<Record<string, DiaryEntry[]>>("/diary"),
  day: (date_str: string) => api.get<DiaryEntry[]>("/diary", { date_str }),
  add: (entry: DiaryEntryIn) => api.post<{ ok: boolean }>("/diary", entry),
  remove: (date_str: string, idx: number) => api.delete<{ ok: boolean }>(`/diary/${date_str}/${idx}`),
  tags: (date_str: string) => api.get<string[]>("/diary/tags", { date_str }),
  detectTags: (text: string) => api.post<DetectTagsResult>("/diary/detect-tags", { text }),
  autocomplete: (prefix: string, max_results = 6) =>
    api.get<string[]>("/diary/autocomplete", { prefix, max_results }),
  autocompleteTerms: () => api.get<string[]>("/diary/autocomplete-terms"),
  exportUrl: () => api.fileUrl("/diary/export"),

  uploadAttachment: (date_str: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api.postForm<{ stored_name: string; original_name: string }>(
      `/diary/${date_str}/attachments`,
      form,
    );
  },
  attachmentUrl: (stored_name: string) => api.fileUrl(`/diary/attachments/${stored_name}`),

  harvestStatus: () => api.get<HarvestStatus>("/diary/harvest-status"),
  setHarvestDate: (harvest_date: string | null) =>
    api.post<{ ok: boolean }>("/diary/harvest-date", { harvest_date }),

  upcomingPlan: () => api.get<UpcomingPlan | null>("/diary/plan-check/upcoming"),
  submitPlanCheck: (date: string, summary: string, days_left: number) =>
    api.post<{ job_id: string }>("/diary/plan-check", { date, summary, days_left }),
  submitPlanCheckFeedback: (date: string, summary: string, days_left: number, feedback: string) =>
    api.post<{ job_id: string }>("/diary/plan-check/feedback", { date, summary, days_left, feedback }),

  nutrientList: (flat_limit?: number) =>
    api.get<NutrientEntry[]>("/diary/nutrient", { flat_limit }),
  nutrientDay: (date_str: string) => api.get<NutrientEntry[]>("/diary/nutrient", { date_str }),
  addNutrient: (date: string, recipe: NutrientRecipe, symptom = "") =>
    api.post<{ idx: number }>("/diary/nutrient", { date, recipe, symptom }),
  analyzeNutrient: (date_str: string, idx: number, recipe: NutrientRecipe, symptom: string) =>
    api.post<{ job_id: string }>(`/diary/nutrient/${date_str}/${idx}/analyze`, {
      date: date_str,
      recipe,
      symptom,
    }),
};
