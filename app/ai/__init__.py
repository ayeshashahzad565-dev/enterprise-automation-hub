"""The AI provider abstraction.

This package is the *only* boundary through which the rest of the codebase
may talk to a large-language-model API. It defines a single, narrow
capability (``AiProvider.complete``, see ``app.ai.interfaces``) and one or
more concrete implementations (``app.ai.providers``) — nothing here knows
about requests, workflows, approvals, or any other domain concept. Prompt
construction, business-data gathering, caching, and graceful fallback all
live one layer up, in ``app.services.ai_insight_service.AiInsightService``:
the single Application Service permitted to import from this package.

Modeled directly on ``app.notifications``' ``EmailProvider``/
``SmtpEmailProvider`` split: a ``Protocol`` for the raw capability, and a
concrete implementation that validates its own configuration eagerly
(raising ``AiConfigurationError``) rather than degrading silently.
"""

from __future__ import annotations
