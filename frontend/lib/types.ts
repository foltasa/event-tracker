// Source of truth for these shapes is backend/app/schemas/*.py and backend/app/ingestion/normalize.py.
// Keep this file in sync with those modules — the JSON fixtures in fixtures/ exercise both sides.

export type EventCategory =
  | "music" | "arts" | "food" | "sports" | "tech"
  | "outdoor" | "film" | "theater" | "family" | "other";

export type Sentiment = "like" | "dislike";
export type LLMProvider = "openai" | "anthropic";
export type ChatRole = "user" | "assistant" | "tool";
export type ToolStatus = "ok" | "error";

export interface EventCard {
  id: string;
  title: string;
  summary: string | null;
  start_datetime: string;   // ISO 8601
  end_datetime: string | null;
  venue_name: string | null;
  venue_address: string | null;
  category: EventCategory;
  tags: string[];
  price_min: number | null;
  price_max: number | null;
  is_free: boolean;
  currency: string;
  image_url: string | null;
  source_url: string;
  source: string;
  is_active: boolean;
}

export interface EventWithContext extends EventCard {
  user_sentiment: Sentiment | null;
  user_comment: string | null;
  is_saved: boolean;
}

export interface UserSettings {
  tool_toggles: Record<string, boolean>;
  llm_provider: LLMProvider;
  llm_model: string | null;
}

export interface ChatTokenUsage {
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
}

export interface DigestPick {
  event: EventCard;
  justification: string;
}

export interface DigestResponse {
  date: string;             // ISO date (YYYY-MM-DD)
  picks: DigestPick[];
  generated_at: string;     // ISO 8601
  is_cached: boolean;
}

export interface EventsFeedResponse {
  events: EventWithContext[];
  total: number;
  page: number;
  page_size: number;
}

export interface FeedbackCreate {
  event_id: string;
  sentiment: Sentiment;
  comment: string | null;
}

export interface FeedbackResponse {
  id: string;
  event_id: string;
  sentiment: Sentiment;
  comment: string | null;
  created_at: string;
  updated_at: string;
}

export interface CalendarEntry {
  id: string;
  event: EventCard;
  saved_at: string;
}

export interface CalendarResponse {
  entries: CalendarEntry[];
}

export interface UserProfileResponse {
  city: string;
  interest_tags: string[];
  about_me: string | null;
  taste_summary: string | null;
  settings: UserSettings;
}

export interface UserProfileUpdate {
  interest_tags?: string[];
  about_me?: string | null;
}

export interface OnboardingRequest {
  interest_tags: string[];
  about_me: string | null;
}

export interface SettingsUpdate {
  tool_toggles?: Record<string, boolean>;
  llm_provider?: LLMProvider;
  llm_model?: string | null;
}

export interface ChatRequest {
  message: string;
  session_id: string;
}

export type ChatChunk =
  | { type: "token";      content: string }
  | { type: "tool_start"; tool_name: string }
  | { type: "tool_end";   tool_name: string; status: ToolStatus }
  | { type: "done";       token_usage: ChatTokenUsage }
  | { type: "error";      message: string };

export interface ChatMessageResponse {
  id: string;
  session_id: string;
  role: ChatRole;
  content: string;
  tool_name: string | null;
  token_usage: ChatTokenUsage | null;
  created_at: string;
}

export interface UsageDay {
  date: string;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
}

export interface UsageRollupResponse {
  today: ChatTokenUsage;
  last_7_days: UsageDay[];
}
