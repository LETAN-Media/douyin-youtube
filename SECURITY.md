# Security Policy

The **ToolNet Publishing Platform** team takes the security and integrity of our media automation and publishing ecosystem seriously. This policy outlines supported versions, vulnerability disclosure procedures, and architectural security standards.

---

## Supported Versions

Security updates and bug fixes are actively maintained for the `main` branch.

| Component | Version / Environment | Supported |
| :--- | :--- | :--- |
| `backend/` (Douyin) | Python 3.12 / FastAPI | :white_check_mark: Active |
| `backend_facebook/` (Facebook) | Python 3.12 / FastAPI | :white_check_mark: Active |
| `backend_tiktok/` (TikTok) | Python 3.12 / FastAPI | :white_check_mark: Active |
| `backend_audio/` (Audio) | Python 3.12 / FastAPI / FFmpeg | :white_check_mark: Active |
| `dashboard/` (Control Panel) | Next.js 16.3 / React 19 / Node.js 22 | :white_check_mark: Active |

---

## Reporting a Vulnerability

If you discover a security vulnerability within this repository, **please do not disclose it publicly** through public GitHub issues or discussions.

### Disclosure Process
1. **Initial Report**: Please contact the maintainers privately via the repository security reporting feature or email the engineering team directly at `security@letanmedia.com` (or create a private GitHub Security Advisory).
2. **Details to Include**:
   - Component / service affected (`backend`, `backend_facebook`, `backend_tiktok`, `backend_audio`, or `dashboard`).
   - Detailed description of the vulnerability and attack vector.
   - Proof-of-concept (PoC) steps or sample payload to reproduce the issue safely.
   - Potential impact assessment.
3. **Response Timeline**:
   - **Initial Response**: Within 48 hours of receipt.
   - **Triage & Status Update**: Within 5 business days.
   - **Remediation & Patch**: Target resolution within 14 business days, depending on severity.

---

## Architectural Security Principles

### 1. Zero Client Credential Exposure
- **Server-Side API Proxying**: The Next.js dashboard routes all administrative operations through server-side handlers (`dashboard/app/api/`).
- **Secret Confinement**: Administrative bearer tokens (`ADMIN_TOKEN`, `DOUYIN_ADMIN_TOKEN`, `FACEBOOK_ADMIN_TOKEN`, `TIKTOK_ADMIN_TOKEN`, `AUDIO_API_TOKEN`) and OAuth secrets (`GOOGLE_CLIENT_SECRET`) are never injected into browser bundles or client-side runtime environments.
- **Environment Variable Rules**: No secret key or authentication token may ever use the `NEXT_PUBLIC_` prefix.

### 2. OAuth 2.0 & CSRF Defenses
- **Cryptographic State Validation**: The YouTube OAuth flow generates a cryptographically random `state` parameter linked to the target pipeline/destination.
- **Single-Use Verification**: State parameters are stored in the database with strict expiration windows and are invalidated immediately upon first consumption to prevent replay and CSRF attacks.

### 3. Tenant & Workspace Boundary Enforcement
- **Multi-Tenant Isolation**: Database queries enforce tenant/workspace scoping to eliminate Insecure Direct Object Reference (IDOR) vulnerabilities across different channel pipelines.
- **Administrative Token Authorization**: Endpoints mutating pipeline configuration, scheduling, or credentials require valid `Bearer` authentication verified on each request.

### 4. Upstream Request Sanitization
- **SSRF Prevention**: All creator URLs, profile links, and redirect targets are validated against authorized domain patterns (e.g. `douyin.com`, `facebook.com`, `tiktok.com`) before invoking upstream media scrapers or HTTP resolvers.
- **Media Ingestion Integrity**: Downloaded video and audio assets are processed through standard FFprobe and FFmpeg stream validation to identify corrupted or malicious file payloads prior to YouTube ingestion.
