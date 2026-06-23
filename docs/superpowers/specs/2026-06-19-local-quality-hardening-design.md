# Local Quality Hardening Design

## Scope

Close three evidence-backed gaps found after the successful local build pass: Dashboard API confidentiality, cron parser correctness, and document-link portability.

## Access Design

All non-public Dashboard paths require authorization. When `ANT_COLONY_AUTH_TOKEN` is configured, a matching Bearer token is required for local and remote callers. When it is absent, loopback callers remain allowed for internal capability callbacks, while non-loopback callers receive a service-unavailable authentication-configuration response. Public paths remain limited to `/`, `/docs`, `/docs/oauth2-redirect`, `/redoc`, and `/openapi.json`.

## Scheduling Design

The local parser continues to avoid a new scheduling dependency. It accepts compact and spaced intervals (`every 2h`, `every 30 min`) plus five-field cron expressions whose fields are integers or `*`. It calculates the next matching minute, honors day/month/weekday, and safely falls back one hour for empty or unsupported expressions.

## Document URL Design

The direct WeCom Bot file response remains unchanged. Legacy application fallback links use `ANT_COLONY_DOCUMENT_BASE_URL`, default to the local dashboard address, strip trailing slashes, and percent-encode the filename path segment.

## Verification

Each behavior is introduced through a failing regression test. Completion requires focused tests, the complete test suite, package build, runtime-name static checks, Bandit high-severity scan, and dependency audit.
