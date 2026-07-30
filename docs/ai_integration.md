# AI Integration

Every AI-generated touchpoint in the platform — request/approval summaries,
workflow recommendations, bottleneck/policy/operational insights, executive
summaries, and a natural-language dashboard assistant — is served by one
Application Service, `app.services.ai_insight_service.AiInsightService`, and
one router, `app.api.routers.ai` (`/api/v1/ai/*`). No other service in the
codebase imports the AI provider abstraction or builds a prompt.

## Checklist → method mapping

Several requested features describe the same underlying data from different
angles; rather than duplicating near-identical methods, one method backs
each, stated explicitly here so the mapping is visible and correctable:

| Requested feature | `AiInsightService` method | Data source (read-only) |
|---|---|---|
| AI request summaries | `summarize_request` | `RequestService.get_request` + `CommentService.list_comments` |
| AI approval summaries | `summarize_approval` | same, plus `RequestService.get_workflow_progress` (decision-oriented framing) |
| AI workflow recommendations **+** Suggest workflow improvements | `suggest_workflow_improvements` | `WorkflowDefinitionService.get_active_version` + `OperationalAnalyticsEngine.get_bottlenecks`/`get_approval_delays` scoped by `request_type` |
| AI bottleneck explanations **+** Explain workflow delays | `explain_bottlenecks` | `OperationalAnalyticsEngine.get_bottlenecks`/`get_approval_delays` (company-wide) |
| AI policy recommendations | `recommend_policies` | same operational data, different prompt framing |
| AI-generated operational insights | `generate_operational_insights` | same operational data + `get_sla_metrics`/`get_executive_kpis`, broader narrative framing |
| Executive summaries | `generate_executive_summary` | `ReportingEngine.build_executive_summary` (also the fallback) |
| Natural language analytics **+** AI dashboard assistant | `ask_assistant` | `DashboardService.get_dashboard_summary` + `OperationalAnalyticsEngine.get_executive_kpis` as grounding context, plus the caller's question and client-sent history |

## The provider abstraction

`app/ai/` is the only boundary through which the codebase talks to an LLM
API, modeled directly on `app.notifications`' `EmailProvider`/
`SmtpEmailProvider` split:

- `app.ai.interfaces.AiProvider` (`Protocol`) — the lowest-level capability:
  turn one system/user prompt pair into one `AiCompletion`. Knows nothing
  about requests, workflows, or any other domain concept.
- `app.ai.providers.openai_provider.OpenAiProvider` /
  `app.ai.providers.anthropic_provider.AnthropicProvider` — concrete
  implementations calling each vendor's REST API directly via `httpx`
  (already a dependency; no vendor SDK is introduced). Both validate
  `api_key`/`model` eagerly at construction, raising `AiConfigurationError`
  rather than degrading silently, and retry transient network/5xx/429
  failures via the existing `app.utils.retry.RetryPolicy`.
- `AI_PROVIDER=groq` — a third option, dispatched in
  `app.bootstrap._build_ai_provider` to the *same* `OpenAiProvider` class,
  just constructed with `base_url="https://api.groq.com/openai/v1"`. No
  separate provider implementation exists or is needed: Groq's Chat
  Completions API is wire-compatible with OpenAI's (identical request/
  response shape, identical Bearer-token auth), so this is a configuration
  variant, not a new integration. A practical option when an OpenAI/
  Anthropic paid key isn't available yet, since Groq offers a free tier
  (console.groq.com). Model names are Groq's own catalog (e.g.
  `llama-3.3-70b-versatile`), passed through as an opaque string exactly
  like every other provider's `AI_MODEL`.
- Every call failure — auth, rate limit, timeout, unparsable response — is
  raised as a single `AiProviderError`. One type is sufficient since every
  caller (in practice, only `AiInsightService`) handles every failure mode
  identically: log a warning and fall back to non-AI content.

## Graceful fallback

`app.bootstrap._build_ai_provider` mirrors `_build_email_sender`: with
`AI_PROVIDER` unset, or construction failing despite it being set, it logs
and returns `None` rather than crashing the process. `AiInsightService`
accepts `ai_provider: AiProvider | None` and implements the "graceful
fallback" requirement **once**, centrally
(`AiInsightService._complete_or_fallback`) — every public method calls this
single helper rather than each hand-rolling its own `try`/`except`.

Every method's fallback is a deterministic string built from data already
fetched for the AI prompt (zero extra cost), so a caller always sees
*something* useful, never a bare error:

- `summarize_request`/`summarize_approval` → a one-liner from the request's
  own title/status/comment count.
- `explain_bottlenecks`/`recommend_policies`/`generate_operational_insights`/
  `suggest_workflow_improvements` → the raw bottleneck/delay figures
  formatted as plain sentences.
- `generate_executive_summary` → **`ReportingEngine.build_executive_summary(...).narrative`
  verbatim** — this already-existing, template-based summary doubles as the
  AI feature's own fallback, not something built new.
- `ask_assistant` → a fixed "AI assistant is currently unavailable" message —
  the one case where no deterministic answer to an arbitrary question is
  possible.

The frontend (`AiInsightCard`) renders `is_fallback` visibly: a fallback
response shows a muted "AI unavailable, showing a computed summary" caption
instead of the usual "AI" badge, so a viewer can never mistake fallback
content for genuine AI output.

## The dashboard assistant is grounded, not agentic

`ask_assistant` answers from a fixed snapshot of the caller's own
already-authorized dashboard/KPI data inserted into the prompt — it never
executes a query the model itself constructs. Building a tool-calling agent
with live database access was not requested and would be a materially
larger security/cost surface than this feature needs. It is also
deliberately **non-streaming** (one request → one JSON response, shown
behind a loading state) — there is no SSE/streaming precedent anywhere else
in this application's frontend, and introducing one wasn't requested.
Conversation history is not persisted server-side; the client resends prior
turns as `history` on each call.

## Caching

Reuses `app.utils.cache.ResponseCache`/`TTLCache` and
`app.utils.redis_cache.RedisCache` verbatim — the same mechanism
`AnalyticsEngine` already uses, with no new caching infrastructure. Two
TTLs, both a disclosed, bounded staleness window (not silently
approximate):

- **300 seconds** for per-entity summaries (request/approval) — short,
  since new comments should show up reasonably soon.
- **900 seconds** for company-wide insights (bottlenecks, policy,
  operational insights, executive summary, workflow improvements) — longer,
  since these are the most expensive calls and the underlying figures
  change slowly.

`ask_assistant` is **not cached** — arbitrary question text plus per-call
history makes cache keys low-hit-rate, an intentional exclusion. Cache-hit
tracking (`AiInsight.cached`) is accurate per-call: a hit re-marks the
stored value `cached=True` on return rather than being baked in at
computation time, so a fresh computation is never mislabeled as cached or
vice versa.

## Authorization

Every method reuses whichever existing service's own authorization already
applies — no new visibility rule is introduced:

| Method | Access |
|---|---|
| `summarize_request`, `summarize_approval` | Requester, an assigned approver, or admin — identical to `RequestService.get_request`'s own rule. The two differ only in prompt framing, not visibility. |
| `suggest_workflow_improvements` | Admin only — matches the Workflow Designer page's own admin-only gate. |
| `explain_bottlenecks`, `recommend_policies`, `generate_operational_insights`, `generate_executive_summary`, `ask_assistant` | Approver or admin — the same `_ANALYTICS_ROLES` least-privilege policy `AnalyticsService` already applies to organization-wide data. |

## Endpoints

| Method | Path | `AiInsightService` method |
|---|---|---|
| `GET` | `/ai/requests/{request_id}/summary` | `summarize_request` |
| `GET` | `/ai/requests/{request_id}/approval-summary` | `summarize_approval` |
| `GET` | `/ai/workflows/{request_type}/improvements` | `suggest_workflow_improvements` |
| `GET` | `/ai/operations/bottlenecks` | `explain_bottlenecks` |
| `GET` | `/ai/operations/policy-recommendations` | `recommend_policies` |
| `GET` | `/ai/operations/insights` | `generate_operational_insights` |
| `GET` | `/ai/operations/executive-summary` | `generate_executive_summary` |
| `POST` | `/ai/assistant/ask` | `ask_assistant` |

Every route additionally depends on `enforce_ai_rate_limit`
(`ai_per_minute`, default 20/min per authenticated user) on top of the
general `enforce_rate_limit` — deliberately tighter than
`search_per_minute`'s 120/min, since each call may invoke a paid,
multi-second external AI provider request rather than a local database
query.

## Frontend

- `features/ai/components/ai-insight-card.tsx` — the generic card every
  read-only insight renders through: loading skeleton, error state with
  retry, and content with an "AI" badge or fallback caption depending on
  `is_fallback`.
- `features/ai/components/ai-assistant-panel.tsx` — the chat-style
  assistant panel (textarea + message list), client-side conversation
  state only.
- Placement: an "AI summary" card on the request detail page and the
  approval detail view; an "AI-suggested improvements" banner on the
  Workflow Designer page; "Bottleneck explanation" / "Policy
  recommendations" / "Operational insights" cards on the Analytics page's
  Intelligence tab; an "AI executive summary" card on the Executive tab,
  alongside (not replacing) the existing, non-AI `ExecutiveNarrativePanel`
  whose narrative is this feature's own fallback content; an "Ask about
  your data" section embedding the assistant panel on the Dashboard page.
