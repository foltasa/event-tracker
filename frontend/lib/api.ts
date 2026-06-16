// Single API client used by every page/component. Switches between a real FastAPI
// backend and the JSON fixtures under fixtures/ via NEXT_PUBLIC_MOCK_MODE.
//
// Mutations in mock mode return a plausible response and log to console — they do
// NOT mutate the fixture files.

import type {
  CalendarEntry,
  CalendarResponse,
  ChatChunk,
  ChatRequest,
  DigestResponse,
  EventsFeedResponse,
  EventWithContext,
  FeedbackCreate,
  FeedbackResponse,
  OnboardingRequest,
  SettingsUpdate,
  UsageRollupResponse,
  UserProfileResponse,
  UserProfileUpdate,
  UserSettings,
} from "@/lib/types";

const MOCK = process.env.NEXT_PUBLIC_MOCK_MODE === "true";
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const USER_ID = process.env.NEXT_PUBLIC_USER_ID ?? "local";

function headers(extra: HeadersInit = {}): HeadersInit {
  return { "Content-Type": "application/json", "X-User-Id": USER_ID, ...extra };
}

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { ...init, headers: headers(init?.headers) });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`API ${res.status} ${path}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

// ---------- Digest ----------

export async function getDigest(): Promise<DigestResponse> {
  if (MOCK) return (await import("@/fixtures/digest.json")).default as DigestResponse;
  return jsonFetch<DigestResponse>("/digest");
}

export async function refreshDigest(): Promise<DigestResponse> {
  if (MOCK) {
    console.info("[mock] POST /digest/refresh");
    return (await import("@/fixtures/digest.json")).default as DigestResponse;
  }
  return jsonFetch<DigestResponse>("/digest/refresh", { method: "POST" });
}

// ---------- Events ----------

export interface EventsQuery {
  page?: number;
  page_size?: number;
  category?: string;
  date_from?: string;
  date_to?: string;
  is_free?: boolean;
  q?: string;
}

export async function getEvents(query: EventsQuery = {}): Promise<EventsFeedResponse> {
  if (MOCK) return (await import("@/fixtures/events.json")).default as EventsFeedResponse;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null) params.set(k, String(v));
  }
  const qs = params.toString();
  return jsonFetch<EventsFeedResponse>(`/events${qs ? `?${qs}` : ""}`);
}

export async function getEventDetail(id: string): Promise<EventWithContext> {
  if (MOCK) return (await import("@/fixtures/event-detail.json")).default as EventWithContext;
  return jsonFetch<EventWithContext>(`/events/${encodeURIComponent(id)}`);
}

// ---------- Feedback ----------

export async function postFeedback(body: FeedbackCreate): Promise<FeedbackResponse> {
  if (MOCK) {
    console.info("[mock] POST /feedback", body);
    const now = new Date().toISOString();
    return { id: `fb_mock_${Date.now()}`, ...body, created_at: now, updated_at: now };
  }
  return jsonFetch<FeedbackResponse>("/feedback", { method: "POST", body: JSON.stringify(body) });
}

export async function deleteFeedback(eventId: string): Promise<void> {
  if (MOCK) {
    console.info("[mock] DELETE /feedback/", eventId);
    return;
  }
  await fetch(`${API_URL}/feedback/${encodeURIComponent(eventId)}`, {
    method: "DELETE", headers: headers(),
  });
}

// ---------- Calendar ----------

export async function getCalendar(): Promise<CalendarResponse> {
  if (MOCK) return (await import("@/fixtures/calendar.json")).default as CalendarResponse;
  return jsonFetch<CalendarResponse>("/calendar");
}

export async function saveToCalendar(eventId: string): Promise<CalendarEntry> {
  if (MOCK) {
    console.info("[mock] POST /calendar/", eventId);
    const detail = (await import("@/fixtures/event-detail.json")).default as EventWithContext;
    const { user_sentiment, user_comment, is_saved, ...card } = detail;
    return { id: `sav_mock_${Date.now()}`, event: card, saved_at: new Date().toISOString() };
  }
  return jsonFetch<CalendarEntry>(`/calendar/${encodeURIComponent(eventId)}`, { method: "POST" });
}

export async function removeFromCalendar(eventId: string): Promise<void> {
  if (MOCK) {
    console.info("[mock] DELETE /calendar/", eventId);
    return;
  }
  await fetch(`${API_URL}/calendar/${encodeURIComponent(eventId)}`, {
    method: "DELETE", headers: headers(),
  });
}

// ---------- Profile & settings ----------

export async function getProfile(): Promise<UserProfileResponse> {
  if (MOCK) return (await import("@/fixtures/profile.json")).default as UserProfileResponse;
  return jsonFetch<UserProfileResponse>("/profile");
}

export async function updateProfile(body: UserProfileUpdate): Promise<UserProfileResponse> {
  if (MOCK) {
    console.info("[mock] PUT /profile", body);
    const current = (await import("@/fixtures/profile.json")).default as UserProfileResponse;
    return { ...current, ...body, interest_tags: body.interest_tags ?? current.interest_tags };
  }
  return jsonFetch<UserProfileResponse>("/profile", { method: "PUT", body: JSON.stringify(body) });
}

export async function postOnboarding(body: OnboardingRequest): Promise<UserProfileResponse> {
  if (MOCK) {
    console.info("[mock] POST /onboarding", body);
    const current = (await import("@/fixtures/profile.json")).default as UserProfileResponse;
    return { ...current, interest_tags: body.interest_tags, about_me: body.about_me };
  }
  return jsonFetch<UserProfileResponse>("/onboarding", { method: "POST", body: JSON.stringify(body) });
}

export async function getSettings(): Promise<UserSettings> {
  if (MOCK) return (await import("@/fixtures/settings.json")).default as UserSettings;
  return jsonFetch<UserSettings>("/settings");
}

export async function updateSettings(body: SettingsUpdate): Promise<UserSettings> {
  if (MOCK) {
    console.info("[mock] PUT /settings", body);
    const current = (await import("@/fixtures/settings.json")).default as UserSettings;
    return {
      tool_toggles: { ...current.tool_toggles, ...(body.tool_toggles ?? {}) },
      llm_provider: body.llm_provider ?? current.llm_provider,
      llm_model: body.llm_model ?? current.llm_model,
    };
  }
  return jsonFetch<UserSettings>("/settings", { method: "PUT", body: JSON.stringify(body) });
}

// ---------- Usage ----------

export async function getUsage(): Promise<UsageRollupResponse> {
  if (MOCK) return (await import("@/fixtures/usage.json")).default as UsageRollupResponse;
  return jsonFetch<UsageRollupResponse>("/usage");
}

// ---------- Chat (streaming) ----------

/**
 * Subscribe to a chat stream. The handler is invoked once per SSE event, in
 * order. In mock mode, the fixture chunks are emitted with ~120ms spacing so
 * the UI can be developed against realistic streaming behaviour.
 */
export async function postChat(req: ChatRequest, onChunk: (chunk: ChatChunk) => void): Promise<void> {
  if (MOCK) {
    const chunks = (await import("@/fixtures/chat-stream.json")).default as ChatChunk[];
    for (const c of chunks) {
      await new Promise((r) => setTimeout(r, 120));
      onChunk(c);
    }
    return;
  }

  const res = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: headers({ Accept: "text/event-stream" }),
    body: JSON.stringify(req),
  });
  if (!res.ok || !res.body) throw new Error(`Chat stream failed: ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE events are separated by a blank line. sse_starlette emits CRLF
    // (`\r\n\r\n`); other servers may use LF (`\n\n`). Accept either.
    const parts = buffer.split(/\r?\n\r?\n/);
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const dataLine = part.split(/\r?\n/).find((l) => l.startsWith("data:"));
      if (!dataLine) continue;
      try {
        onChunk(JSON.parse(dataLine.slice(5).trim()) as ChatChunk);
      } catch {
        // Ignore malformed chunks rather than killing the stream.
      }
    }
  }
}
