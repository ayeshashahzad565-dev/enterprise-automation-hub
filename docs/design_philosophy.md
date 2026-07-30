# Enterprise Automation Hub (EAH)
## Design Philosophy & Interaction Principles

**Version:** 1.0
**Status:** Reference — governs all future page-level redesign work
**Scope:** This document establishes the visual and interaction philosophy only. No page in `app/pages/` is modified by it. It is the standard every subsequent page redesign is reviewed against.

> **Superseded note:** Written against the original Streamlit UI
> (`app/pages/`, `app/pages/components.py`, `app/pages/assets/theme.css`).
> The Presentation Layer has since been rebuilt as a Next.js/React frontend
> (`frontend/`), with its own component library (`frontend/src/components/ui`,
> Base UI + Tailwind v4) and typography system
> (`frontend/src/components/patterns/typography.tsx`) fulfilling the same
> "premium enterprise SaaS, not default-widget" intent this document
> describes. The *principles* below (restraint, consistent hover/focus
> affordances, no unstyled defaults) still govern the current frontend;
> the specific file paths and Streamlit widget references do not.

---

## 1. What EAH should feel like

EAH should feel like a premium enterprise SaaS product — not a Streamlit app, not a prototype. A first-time user should assume it was built by a professional product team, not assembled from default widgets.

Reference points for *layout and typography* (Linear), *data presentation* (Stripe Dashboard), and *tables/forms/information density* (GitHub). None of these are to be copied directly — they inform proportion, restraint, and density, not literal visual identity. EAH keeps its own palette (`.streamlit/config.toml`) and its own component vocabulary (`app/pages/components.py`).

The target feeling: **calm, focused, expensive.** Calm means low visual noise. Focused means the page foregrounds the one or two things that matter right now. Expensive means restraint — the absence of anything decorative is itself the signal of quality.

Every screen must answer, in this order, at a glance:

1. **Where am I?** — page header + breadcrumb (`navigation.render_breadcrumbs`), not just a heading.
2. **What requires my attention?** — pending items, alerts, escalations, surfaced above the fold, not buried in a table.
3. **What can I do?** — actions are visible and contextual, not hidden behind generic buttons.
4. **What changed?** — status, timestamps, and deltas are always present, not just current-state snapshots.
5. **What should I do next?** — the primary action on any page should be visually unambiguous (one `type="primary"` button per view, not several competing for weight).

If a page cannot answer all five without scrolling or hunting, it fails this brief regardless of how polished its components look individually.

---

## 2. Explicit anti-patterns

These are rejected outright, not "used sparingly":

- Decorative graphics or illustrations
- Glassmorphism, neumorphism
- Gradients as decoration (a single subtle gradient used to communicate state, e.g. a progress bar fill, is not this)
- Oversized cards with excess internal padding chosen for "breathing room" rather than legibility
- Animation that exists to be noticed rather than to confirm an action
- Color used for variety rather than meaning
- Heavy shadows / elevation for its own sake (EAH already sets `showWidgetBorder = true` / `showSidebarBorder = true` in `config.toml` — borders, not shadows, are the primary depth cue)
- Whitespace added because a layout "looked empty," rather than to separate logically distinct groups

If a proposed change to any page cannot be justified by one of the principles in this document, it doesn't belong in EAH.

---

## 3. Visual hierarchy priority

Three tiers, applied consistently across every page:

| Priority | Content | Treatment |
|---|---|---|
| **Highest** | Critical actions, pending approvals, alerts | Above the fold, `type="primary"` or `alert()`/`st.badge` with warning/danger tone, never nested inside a collapsed section |
| **Medium** | Current work in progress | Default card/table treatment, visible without extra clicks but not competing with Highest |
| **Lowest** | Historical / completed information | Behind a tab, expander, or secondary view (e.g. the Audit History tab already added to `requests.py`) — present, not hidden, but not competing for the first glance |

This is why, for example, `requests.py`'s detail view already separates Workflow Timeline / Comments / Audit History into tabs rather than stacking all three in one long scroll — history should never outweigh current state in visual weight.

---

## 4. Color philosophy

Color communicates meaning only. EAH's existing token set in `.streamlit/config.toml` already encodes this and is **not** to be treated as decorative:

- **Green** (`greenColor` / `STATUS_TONE` → `"success"`) — approved, success
- **Amber/orange** (`orangeColor` → `"warning"`) — pending, warning, escalated
- **Red** (`redColor` → `"danger"`) — rejected, critical
- **Blue** (`primaryColor` / `blueColor`) — primary actions and informational states only
- **Gray** (`grayColor`) — secondary, historical, or disabled content

No new color is introduced without a corresponding meaning. `theme.STATUS_TONE`, `theme.TONE_BADGE_COLOR`, and `theme.TONE_STATUS_ICON` (`app/pages/theme.py`) remain the single source of truth for status → color → icon; any future page-level code maps into these tables rather than choosing a color inline.

---

## 5. Typography

Large headings are rare, not the default. EAH's current heading scale (`headingFontSizes = ["28px", "22px", "18px", "16px", "14px", "13px"]`) already caps h1 at 28px — page bodies should reach for h3/h4 (18px/16px) far more often than h1/h2, reserving h1 for the single page title.

Most reading happens at **14–16px** (`baseFontSize = 15` already matches this). Captions (`st.caption`, 13px per the heading scale's tail) carry metadata — timestamps, secondary labels — never primary content.

Hierarchy is built through weight and color (`headingFontWeights`, `textColor` vs. `st.caption`'s muted gray), not through introducing additional font sizes ad hoc.

---

## 6. Density and layout

- **Dashboard-first**: the landing experience for every role leads with what needs attention, not a static welcome screen.
- **Cards only where they clarify hierarchy** — a card that wraps a single line of text or a single metric with no grouping purpose should be a plain row instead. `components.metric_card` and `components.card` are reserved for genuine groupings (a KPI, a stage in a timeline), not used as default containers for everything.
- **Compact tables**: `components.render_table` favors row density over generous row height — this is a data tool, not a marketing page.
- **Filters above content**, always, consistent with the existing `search_bar` / `filter_bar` / `filter_select` placement in `requests.py` and `approvals.py`.
- **Sticky primary actions** where a decision is the point of the page (e.g. Approve/Reject on a stage detail view) so the action never scrolls out of reach on long content.
- Whitespace exists to separate *logical groups* (`st.divider()` between sections, as already used throughout) — it is never added purely to "give a page room."

---

## 7. Interaction philosophy

- **Instant feedback**: every action already routes through `components.run_with_feedback`, which shows a loading state and a flash message — this pattern is mandatory for all future mutations, not optional polish.
- **Hover states**: interactive elements (rows with a "View"/"Review" action, nav items) should have a visible but subtle hover affordance. Within Streamlit's constraints this is expressed through `app/pages/assets/theme.css` (the one CSS file), not per-page inline styles.
- **Micro-interactions only**: any transition added to `theme.css` is capped at **150–200ms**, and must never delay the user's ability to interact (no animation gates input).
- **Progressive disclosure**: secondary detail (audit history, full comment threads, escalation detail) lives behind a tab or expander, not inline in the primary view — already the pattern in `requests.py`'s tabbed detail layout.
- **Keyboard-friendly, minimal clicks**: prefer a single form submission over multi-step wizards; prefer inline actions (buttons in a table row) over "select then navigate then act."
- **Contextual, predictable actions**: an action button's label and position must be the same on every page it appears (e.g. "View" always in the trailing column of a list row, as already standardized across `requests.py` and `approvals.py`).

---

## 8. Consistency rules (non-negotiable across every page)

- Every page uses the same header pattern (`navigation.render_breadcrumbs` + `page_header`/`st.markdown("## ...")`).
- Every list view behaves identically: filters above, `render_table` or the row-with-action pattern below, `pagination_controls` at the bottom.
- Every filter bar behaves identically: `search_bar` / `filter_select` / `filter_bar`, never a page-specific filter widget invented ad hoc.
- Every status is rendered through `components.status_badge` — never a raw string, emoji, or inline color.
- Every detail page follows the same structure: summary → primary actions → progressive-disclosure tabs (timeline / comments / history), as already established in `requests.py` and `approvals.py`.
- Every confirmation follows `components.confirm_action` / `components.danger_button` — no bespoke "are you sure" pattern per page.

Future page redesigns are reviewed against this list first; a page that reinvents a pattern this document already standardizes is a regression, not an improvement.

---

## 9. Components should appear handcrafted

Default Streamlit widget chrome (unbordered containers, default button styling, raw `st.write` dumps) reads as a prototype. Every user-facing element goes through the shared component layer (`app/pages/components.py`) or a native widget configured deliberately (`st.container(border=True)`, `st.badge(...)`, `st.metric(border=True)`) — never left at its unstyled default when a shared component already exists for that purpose.

---

## 10. Success criteria

A first-time user — employee, approver, or admin — should, within the first screen they see, believe this is a commercial platform: calm, information-dense without clutter, unambiguous about what needs their attention and what they can do next. Every subsequent page-level redesign is measured against that bar, and against the consistency rules in Section 8, before it is considered complete.

**Throughout implementation: prefer simplicity over novelty.** When a native Streamlit primitive already achieves the desired effect, it is used as-is rather than wrapped in custom styling for its own sake.
