// Mirrors backend pydantic/dict response shapes (verified via live curl against the FastAPI backend).

export interface OutdoorContext {
  obs_time: string;
  outdoor_temp: number;
  outdoor_rh: number;
  outdoor_vpd: number;
  wind_speed: number;
  wind_dir_kor: string;
  wind_dir_deg: number | null;
  precipitation: number;
  pty: number;
  pty_label: string;
  wf_kor: string;
  source: string;
  abs_humidity: number;
  moisture_deficit: number;
}

export interface EnvironmentCurrent {
  temp: number;
  rh: number;
  co2: number;
  solar: number;
  solar_is_mock: boolean;
  cum_solar: number | null;
  outdoor_temp: number | null;
  wind_speed: number | null;
  wind_dir: number | null;
  rain: string | null;
  timestamp: string;
  data_timestamp: string;
  is_frozen: boolean;
  source: string;
  vpd: number;
  abs_humidity: number;
  saturation_ah: number;
  moisture_deficit: number;
  outdoor: OutdoorContext | null;
}

export interface EnvironmentHistoryPoint {
  timestamp: string;
  temp: number;
  rh: number;
  co2: number;
  solar: number;
  vpd: number;
}

export interface RiskCard {
  icon: string;
  title: string;
  body: string;
  severity: 0 | 1 | 2;
  drugs: string[];
  thumb_url: string;
  pathogen_type: string;
}

export interface PestRiskRow {
  name: string;
  kind: string;
  pathogen_type: string;
  label: string;
  reason: string;
  note: string;
}

export interface EnvironmentRisk {
  overall_severity: 0 | 1 | 2;
  cards: RiskCard[];
  pest_table: PestRiskRow[];
}

export interface GrowthRecord {
  [key: string]: unknown;
  date: string;
  zone: string;
  crop_height_cm: string;
  leaf_count: string;
  fruit_count: string;
  truss_count: string;
  stem_diameter_mm: string;
  truss_height_cm: string;
  notes: string;
}

export interface GrowthAssessment {
  [key: string]: unknown;
}

export interface WeatherAws {
  stn: number;
  obs_time: string;
  temp: number;
  rh: number;
  vpd: number;
  wind_speed: number;
  wind_dir_deg: number;
  wind_dir_kor: string;
  pressure_hpa: number;
  rainfall_60m: number;
  rainfall_day: number;
  dewpoint: number;
  source: string;
  fetched_at: string;
}

export interface WeatherForecastRow {
  date: string;
  time: string;
  TMP: string;
  WSD: string;
  SKY: string;
  PTY: string;
  POP: string;
  REH: string;
  sky_disp: string;
  light_estimate: string;
}

export interface WeatherDailySummary {
  [key: string]: unknown;
}

export interface VentilationHint {
  hint: string;
}

export interface WeatherRefreshResult {
  aws: WeatherAws;
  outdoor: Record<string, unknown>;
  warnings: string[];
  alert_sent: boolean;
}

export interface PriceLedgerRow {
  "거래일자": string;
  "경락일시": string;
  "도매시장": string;
  "법인": string;
  "매매구분": string;
  "부류": string;
  "품목": string;
  "품종": string;
  "출하지": string;
  "단량": string;
  "수량": string;
  "단량당 경락가(원)": number;
  "등급": string;
  "이상값"?: boolean;
}

export interface PriceLedger {
  date: string | null;
  rows: PriceLedgerRow[];
  stats: {
    min: number;
    max: number;
    avg: number;
    count: number;
    outlier_count?: number;
    avg_basis_count?: number;
  };
  origin_market?: {
    "출하지": string;
    "도매시장": string;
    "평균가": number;
    "건수": number;
    "시장평균대비": number;
    "전체평균대비": number | null;
    "산지평균대비": number;
  }[];
  archive?: {
    file?: string;
    added?: number;
    skipped?: number;
    total_rows?: number;
    error?: string;
  };
}

export interface AuctionArchiveSummary {
  file: string;
  rows: number;
  date_start: string | null;
  date_end: string | null;
  origin_count: number;
  market_count: number;
  avg_price: number | null;
}

export interface OriginMarketCycleRow {
  "출하지": string;
  "도매시장": string;
  "월": string;
  "평균가": number;
  "건수": number;
  "시장월평균대비": number;
}

export interface MarketSummaryRow {
  "도매시장": string;
  "평균가": number;
  "건수": number;
}

export interface OriginMarketCycle {
  summary: AuctionArchiveSummary;
  days: number;
  min_count: number;
  rows: OriginMarketCycleRow[];
  market_summary: MarketSummaryRow[];
}

export interface GradeInfo {
  price: number;
  price_kg: number;
  price_str: string;
  price_kg_str: string;
  dod_change: number | null;
  prev_month: number | null;
  prev_year: number | null;
  avg_year: number | null;
}

export interface AllGrades {
  "상": GradeInfo;
  "중": GradeInfo;
  "하": GradeInfo;
  date: string;
  market: string;
  unit: string;
}

export interface GradesByMarket {
  market: string;
  date: string;
  "상": GradeInfo;
  "중": GradeInfo;
  "하": GradeInfo;
}

export interface PriceToday {
  date: string;
  item: string;
  market: string;
  grade: string;
  price: number;
  price_str: string;
  dod_change: number;
  source: string;
}

export interface PriceBoardRow {
  date: string;
  price: number;
  [key: string]: unknown;
}

export interface PriceBoard {
  series: PriceBoardRow[];
  trend: { date: string; trend: number }[];
}

export interface PriceMarketCompareRow {
  market: string;
  date: string;
  price: number;
  [key: string]: unknown;
}

export interface PriceBriefingResult {
  content: string;
  articles: { title: string; media: string; pub_date: string; description: string; link?: string }[];
}

export interface SalesAdvice {
  signal: "출하" | "직거래" | "보통" | "없음";
  ratio: number | null;
  seasonal_avg: number | null;
  next_trend: "상승" | "하락" | "유지" | null;
  headline: string;
  detail_lines: string[];
}

export interface HarvestStrategy {
  horizon_days: number;
  target_date: string;
  action: string;
  temperature_strategy: string;
  rationale: string;
  price: {
    direction: "up" | "down" | "flat" | "unknown";
    change_pct: number | null;
    current_price: number | null;
    projected_price: number | null;
    recent_avg?: number;
    reason: string;
  };
  growth: {
    zones: number;
    avg_height_trend_cm: number | null;
    avg_stem_trend_mm: number | null;
    truss_balance: { "영양생장쪽": number; "생식생장쪽": number; "균형": number };
    readiness: "vegetative_heavy" | "reproductive_heavy" | "balanced" | "unknown";
    reason: string;
  };
  climate: {
    temp: number;
    rh: number;
    constraint: "ok" | "caution" | "risk";
    reason: string;
  };
  caveats: string[];
}

export interface DiagnosisRecord {
  timestamp: string;
  sensor_input: { temp: number; rh: number; co2: number; solar: number };
  vpd_calculated: number;
  outdoor: Record<string, unknown> | null;
  llm_response: string;
  sources: string[];
  farmer_action: string | null;
}

export interface AdviceResult {
  situation: string;
  recommendation: string;
  alert: boolean;
  [key: string]: unknown;
}

export interface AutoDiagnosisSettings {
  enabled: boolean;
  interval_minutes: number;
}

export interface AutoDiagnosisStatus extends AutoDiagnosisSettings {
  last_run_at: string | null;
  next_run_at: string | null;
  last_job_id: string | null;
}

export interface EmailAlertStatus {
  in_cooldown: boolean;
  cooldown_remaining_min: number;
}

export interface ControlLogEntry {
  "시각": string;
  "제어 대상": string;
  "조치": string;
  "설정값": string;
  "구역": string;
  "이유": string;
  "결과": string;
  "센서(당시)": string;
}

export interface NcpmsSearchItem {
  sickKey: string;
  name: string;
  crop: string;
  kind: string;
  thumb: string;
}

export interface NcpmsDetail {
  name: string;
  crop: string;
  symptoms: string;
  condition: string;
  prevention: string;
  chemical: string;
  images: string[];
}

export interface DiaryEntry {
  time: string;
  content: string;
  tags: string[];
  pesticides: string[];
  attachments: (string | { stored_name: string; original_name: string })[];
  updated: string;
}

export interface DetectTagsResult {
  tags: string[];
  diseases: string[];
  disease_info: Record<string, { desc: string; pesticides: string[] }>;
}

export interface HarvestStatus {
  harvest_date: string | null;
  dday: number | null;
  stage: { stage: string; manage: string; timing: string; consistency_note?: string } | null;
}

export interface UpcomingPlan {
  date: string;
  summary: string;
  days_left: number;
  cached_result: string | null;
}

export interface NutrientRecipe {
  n: number;
  p: number;
  k: number;
  ca: number;
  mg: number;
  ec: number;
  ph: number;
}

export interface NutrientEntry {
  date: string;
  time: string;
  recipe: NutrientRecipe;
  symptom: string;
  ai_analysis: string;
  updated: string;
}

export interface SystemConfig {
  has_kma_key: boolean;
  has_at_key: boolean;
  has_kamis_keys: boolean;
  has_ncpms_key: boolean;
  has_naver_keys: boolean;
  has_email_config: boolean;
}

export interface SystemHealth {
  status: string;
  uptime_seconds: number;
  ollama_reachable: boolean;
}

export interface ReportSettings {
  enabled: boolean;
  interval_days: number;
}

export interface ReportStatus extends ReportSettings {
  last_run_at: number | null;
  next_run_at: number | null;
  last_report_id: string | null;
}

export interface ReportListItem {
  report_id: string;
  period: { start: string; end: string; days: number };
  generated_at: string;
  diary_count: number;
  disease_count: number;
}

export interface ReportEnvDaily {
  date: string;
  avg_temp: number;
  min_temp: number;
  max_temp: number;
  avg_rh: number;
  avg_co2: number;
  avg_solar: number;
  reading_count: number;
}

export interface ReportDiaryEntry {
  date: string;
  time?: string;
  content: string;
  tags: string[];
  pesticides: string[];
  [key: string]: unknown;
}

export interface Report {
  report_id?: string;
  period: { start: string; end: string; days: number };
  generated_at: string;
  env: {
    daily: ReportEnvDaily[];
    summary: {
      avg_temp: number;
      max_temp: number;
      min_temp: number;
      avg_rh: number;
      avg_co2: number;
      days_with_data: number;
    } | null;
    coverage_note: string | null;
  };
  diary: ReportDiaryEntry[];
  disease_log: ReportDiaryEntry[];
}
