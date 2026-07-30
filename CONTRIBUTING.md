# Contributing to Enterprise Automation Hub

Thank you for your interest in contributing to Enterprise Automation Hub (EAH). This document describes how to set up a development environment, the conventions this project follows, and what is expected of a pull request before it can be merged.

EAH is a modular monolith by design. Contributions should reinforce that architecture — see the [Architecture Design Document](docs/architecture.md) before proposing any change that introduces a new service, dependency, or infrastructure component.

## Table of Contents

- [Development Setup](#development-setup)
- [Branch Naming](#branch-naming)
- [Commit Conventions](#commit-conventions)
- [Pull Request Guidelines](#pull-request-guidelines)
- [Coding Standards](#coding-standards)
- [Testing Requirements](#testing-requirements)

## Development Setup

1. **Fork and clone the repository.**

```bash
   git clone https://github.com/<your-username>/enterprise-automation-hub.git
   cd enterprise-automation-hub
```

2. **Create a virtual environment and install dependencies, including development tools.**

```bash
   python3.11 -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   pip install -e ".[dev]"
```

   For a fully reproducible install of the exact versions CI tests
   against (rather than whatever the resolver picks from
   `pyproject.toml`'s ranges today), install from the hash-pinned lockfile
   instead: `pip install -r requirements-dev.txt`. Both are kept in sync —
   `requirements-dev.txt` is generated from `pyproject.toml` via
   `pip-compile` and CI fails if it ever drifts out of date.

3. **Configure your environment.**

```bash
   cp .env.example .env
```

   Populate `.env` with a personal or disposable Supabase test project's credentials. Never point local development at a shared staging or production project.

4. **Apply database migrations.**

```bash
   alembic upgrade head
```

5. **Verify your setup by running the fast unit suite.**

```bash
   pytest -m unit
```

For the full Playwright end-to-end suite (login/logout, requests,
approvals, analytics, Platform Administration, tenant isolation, session
expiry) against a real local Supabase stack, see
[`frontend/e2e/README.md`](frontend/e2e/README.md).

For the real-database integration suite (repository CRUD, schema
constraints, and Row-Level Security policy enforcement — `pytest
tests/integration`), which needs its own dedicated test database and runs
in its own CI job, see [`tests/integration/README.md`](tests/integration/README.md).

## Branch Naming

Branch names should be short, lowercase, hyphen-separated, and prefixed by type:

| Prefix | Use For |
|---|---|
| `feature/` | New functionality |
| `fix/` | Bug fixes |
| `chore/` | Tooling, dependencies, configuration |
| `docs/` | Documentation-only changes |
| `refactor/` | Internal restructuring with no behavior change |
| `test/` | Test-only additions or changes |

Example: `feature/department-queue-assignment`, `fix/optimistic-lock-race`, `docs/update-deployment-guide`.

## Commit Conventions

This project follows [Conventional Commits](https://www.conventionalcommits.org/).