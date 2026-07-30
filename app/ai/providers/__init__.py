"""Concrete ``AiProvider`` implementations.

Each module here implements ``app.ai.interfaces.AiProvider`` against one
vendor's REST API via plain ``httpx`` calls — no vendor SDK is introduced,
consistent with the fixed technology stack (the same choice
``app.notifications.email_sender.SmtpEmailProvider`` makes for SMTP via
stdlib ``smtplib`` rather than a third-party mail library).
"""

from __future__ import annotations
