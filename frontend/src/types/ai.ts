/**
 * Frontend-owned types for AI-generated insights (`/api/v1/ai/*`), defined
 * independently of the backend's Pydantic schemas, matching the convention
 * every other `types/*.ts` file in this project follows.
 */

/** The result of every `/ai/*` call — either genuine AI-generated text, or
 * a deterministic, computed fallback when no provider is configured or the
 * provider call failed. Always render `is_fallback` visibly (see
 * `AiInsightCard`) rather than presenting fallback content as if it were
 * AI-written. */
export interface AiInsight {
  text: string;
  generated_by: string | null;
  is_fallback: boolean;
  cached: boolean;
  generated_at: string;
}

export interface AiChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface AskAssistantBody {
  question: string;
  history?: AiChatTurn[];
}
