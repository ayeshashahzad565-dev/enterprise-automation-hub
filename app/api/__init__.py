"""FastAPI Presentation Layer.

The first physical HTTP binding for the REST contract already fully
specified in ``docs/api_design.md`` — every route in this package calls
an existing Application Service (or, where no service method exists for
a narrow read, an existing repository directly, per established
composition-root precedent) exactly as ``app.pages`` already does.
This package contains no business logic of its own.
"""

from __future__ import annotations
