# Contributing to ToolNet Publishing Platform

Thank you for your interest in contributing to the **ToolNet Publishing Platform**! This document provides guidelines and workflows for contributing code, documentation, and enhancements to our multi-platform video automation and AI publishing ecosystem.

---

## Table of Contents
- [Code of Conduct](#code-of-conduct)
- [Development Workflow](#development-workflow)
  - [Branching Strategy](#branching-strategy)
  - [Commit Message Conventions](#commit-message-conventions)
  - [Pull Request Process](#pull-request-process)
- [Coding Standards](#coding-standards)
  - [Python (Backend Services)](#python-backend-services)
  - [TypeScript & React (Dashboard)](#typescript--react-dashboard)
- [Testing & Quality Assurance](#testing--quality-assurance)
  - [Running Backend Tests](#running-backend-tests)
  - [Running Dashboard Checks](#running-dashboard-checks)
- [Security Guidelines](#security-guidelines)

---

## Code of Conduct

We are committed to providing a professional, inclusive, and collaborative environment. All contributors and maintainers are expected to conduct themselves respectfully, offer constructive feedback, and maintain the integrity and security of the platform.

---

## Development Workflow

### Branching Strategy
- `main`: Production-ready branch. Direct pushes to `main` must be fast-forward only.
- Feature branches: Use descriptive prefixes when developing new features or resolving issues:
  - `feat/<feature-name>`: New functionality (e.g. `feat/audio-waveform-preview`)
  - `fix/<issue-name>`: Bug fixes (e.g. `fix/tiktok-url-sanitizer`)
  - `docs/<doc-name>`: Documentation improvements (e.g. `docs/api-reference`)
  - `refactor/<module>`: Code restructuring without functional alterations
  - `ci/<workflow>`: CI/CD enhancements

### Commit Message Conventions
We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>(<optional scope>): <short description>

[optional body]

[optional footer(s)]
```

**Common types**:
- `feat`: A new feature or capability
- `fix`: A bug fix or error correction
- `docs`: Documentation changes
- `refactor`: Code changes that neither fix a bug nor add a feature
- `test`: Adding or correcting tests
- `ci`: CI/CD workflow changes or build configuration

*Example*:
```
feat(tiktok): add pipeline-level ai prompt configuration
fix(youtube): resolve csrf state validation in oauth redirect
docs: update architecture mermaid diagrams in readme
```

### Pull Request Process
1. **Fork or Branch**: Create your feature or fix branch from the latest `main`.
2. **Implement Changes**: Keep changes focused and atomic.
3. **Write Regression Tests**: Every functional modification or bug fix must include corresponding unit/regression tests.
4. **Local Verification**: Ensure all tests pass locally before opening a pull request.
5. **Open PR**: Provide a clear description of the problem, solution, modified files, and test results.

---

## Coding Standards

### Python (Backend Services)
- **Runtime**: Python `3.12+`.
- **Framework**: FastAPI with asynchronous handlers (`async def`).
- **Validation**: Pydantic v2 schemas for all request/response models.
- **Database Access**: SQLAlchemy 2.0 select syntax or LibSQL client repositories.
- **Code Style**:
  - Follow PEP 8 guidelines.
  - Use explicit type annotations for function signatures and return values.
  - Avoid global state; encapsulate logic within modular service classes or route dependencies.
  - Use structured logging instead of raw `print` statements.

### TypeScript & React (Dashboard)
- **Runtime & Tools**: Node.js `22.x LTS`, Next.js 16 (App Router), React 19.
- **Language**: TypeScript 5.7 in strict mode (`"strict": true`).
- **Architecture**:
  - Default to React Server Components (RSC) unless interactivity, client state, or browser APIs are required (`"use client"`).
  - All communication with backend microservices must route through server-side proxies in `dashboard/app/api/` to shield admin tokens from client-side bundles.
  - Never prefix backend API tokens or secrets with `NEXT_PUBLIC_`.
- **Styling**: Tailwind CSS utility classes; avoid inline styles.

---

## Testing & Quality Assurance

The platform relies on automated testing to prevent regressions. All pull requests must pass the CI suite.

### Running Backend Tests

#### 1. Douyin Service (`backend/`)
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest pytest-asyncio
DATABASE_PROVIDER=sqlite DATABASE_URL=sqlite:////tmp/test_douyin.db ADMIN_TOKEN=test-token WORKER_ENABLED=false PYTHONPATH=. pytest tests/
```

#### 2. Facebook Reels Service (`backend_facebook/`)
```bash
cd backend_facebook
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest pytest-asyncio
ADMIN_TOKEN=test-token PYTHONPATH=. pytest tests/
```

#### 3. TikTok Service (`backend_tiktok/`)
```bash
cd backend_tiktok
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest pytest-asyncio
ADMIN_TOKEN=test-token PYTHONPATH=. pytest tests/
```

#### 4. Audio Stories Service (`backend_audio/`)
```bash
cd backend_audio
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest pytest-asyncio
ADMIN_TOKEN=test-token PYTHONPATH=. pytest tests/
```

### Running Dashboard Checks
```bash
cd dashboard
npm ci
npm run lint          # ESLint verification
npm run build         # Next.js production compilation and TypeScript verification
```

---

## Security Guidelines

- Never commit credentials, private keys, API keys, or `.env` files to the repository.
- Use mock credentials and isolated SQLite database files (`/tmp/*_test.db`) during automated testing.
- For vulnerability reports or sensitive disclosures, please follow our [Security Policy](SECURITY.md).
