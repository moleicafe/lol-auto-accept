# Security Audit — League Auto Accept

**Date:** 2026-07-10 · **Version audited:** v1.1.0 (`main`) · **Auditor:** internal defensive review

## Scope & threat model

League Auto Accept is a **Windows desktop app with no server component**. It opens no
listening sockets and exposes no HTTP routes, webhooks, or admin surfaces (verified:
no `bind`/`listen`/server frameworks in shipped code; the only server anywhere is a
fake LCU bound to 127.0.0.1 inside the test suite). Its entire network surface is
**outbound**:

| Connection | Direction | Auth | TLS | Data |
|---|---|---|---|---|
| `https://127.0.0.1:<port>` (League client REST) | outbound, loopback | HTTP basic `riot:<token>` | `verify=False` — **accepted by design** (Riot's client uses a self-signed cert; traffic never leaves loopback) | game-client state |
| `wss://127.0.0.1:<port>/` (League client events) | outbound, loopback | same token | `CERT_NONE` — same rationale | game-client events |
| `https://lol-api-champion.op.gg` (GET only) | outbound, internet | none (public data) | verified (httpx default) | champion id/position only |

There is no database, no SQL/NoSQL, no subprocess/`eval`/`pickle` usage, no
user-supplied URL fetching (SSRF N/A — the op.gg URL is built from an integer
champion id and a fixed position map), and no LLM/AI features (Phase 4 N/A).

## The one runtime secret

The League client's auth token is read from the running `LeagueClientUx.exe`
command line (Riot's own mechanism), held in memory in a frozen dataclass, used
only for loopback auth, and is **never logged and never persisted** (verified:
all log statements reviewed; `config.json` serializes only the settings
dataclass, which has no token field).

## Findings

Severity — 0 Critical · 0 High · 2 Medium (both fixed) · 4 Low (accepted/backlog)

| # | Sev | Location | Issue | Status |
|---|---|---|---|---|
| 1 | Medium | `.github/workflows/ci.yml` | No `permissions:` block → workflow token got default (broader) permissions | **Fixed** — `permissions: contents: read` |
| 2 | Medium | dev venv | `pip` 24.0 had 5 known CVEs (dev tooling only; not shipped in the exe) | **Fixed** — upgraded; `pip-audit` now reports 0 known vulns across all deps |
| 3 | Low | `src/laa/__main__.py:17` | Single-instance mutex uses the `Global\` namespace: on a *shared* Windows machine another local user could pre-create the name and prevent the app from starting (local griefing only; no data exposure) | Backlog — switch to per-session `Local\` namespace |
| 4 | Low | `src/laa/lcu/connector.py:89,103-104` | LCU TLS verification disabled. Required for Riot's self-signed loopback cert and low practical risk, but could be hardened by pinning Riot's published root CA instead of `CERT_NONE` | Accepted; optional hardening |
| 5 | Low | `.github/workflows/ci.yml` | Actions pinned by tag (`@v4`/`@v5`) rather than commit SHA — a compromised tag could run modified action code | Backlog — pin to SHAs if supply-chain posture matters |
| 6 | Low | release exe | Unsigned binary → SmartScreen warning trains users to click through; PyInstaller onefile also self-extracts to `%TEMP%` at runtime (standard behavior) | Accepted — code-signing cert is the fix; cost/benefit call |

Phase 1 (secrets) came back **clean**: pattern scan over the working tree and the
full git history found no keys/tokens/passwords; no env/secret/db files are
tracked; `.gitignore` now also preventively excludes `.env*`, `*.pem`, `*.key`.

Injection review (Phase 3 analogues): all LCU request bodies go through
parameterized `json=` payloads (never string-built); dynamic URL path segments are
integers or fixed-map values originating from the user's own local client;
user-configurable text (lobby message) is sent only as a JSON string value to the
local client. UI renders external strings (champion names, log lines) as plain
text widgets — no HTML interpretation.

## Continuous checks (added in this audit)

The `security` job in [.github/workflows/ci.yml](.github/workflows/ci.yml) now runs
on every push and PR:
- **gitleaks** secret scan over the **full git history**
- **pip-audit** dependency vulnerability audit of the installed runtime deps

A "protected endpoints reject unauthenticated requests" smoke test is
intentionally absent: the app has no endpoints. If a server surface is ever
added, add that smoke test in the same job.

**Re-run locally:**

```powershell
# dependency audit
.venv\Scripts\pip-audit --skip-editable

# secret scan (patterns over tree + history)
git grep -nIiE "sk-[A-Za-z0-9]{10,}|api[_-]?key\s*[:=]|Bearer |BEGIN (RSA|EC|OPENSSH|PGP|PRIVATE)"
git log -p --all | grep -inE "sk-[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{16}|BEGIN (RSA|EC|OPENSSH|PGP|PRIVATE)"
```
