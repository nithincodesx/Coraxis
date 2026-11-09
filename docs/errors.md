# Coraxis — RFC 7807 Error Catalogue

This document enumerates every error code the Coraxis API can return. All error
responses are served as `application/problem+json` with a stable `code` field
that clients can branch on, and a human-readable `detail`.

The `type` URI of every error is
`https://github.com/nithincodesx/Coraxis/blob/main/docs/errors.md#<code>`.

---

## Error hierarchy

| Code | HTTP status | Title | When it occurs | Client remediation |
|------|-------------|-------|----------------|--------------------|
| `internal_error` | 500 | Internal Server Error | An unexpected exception occurred. Logged with full traceback; nothing leaks to the client. | Retry later. Quote the `request_id` when reporting. |
| `validation_error` | 422 | Validation Error | Request body or query parameters failed schema validation (Pydantic/FastAPI). Includes an `errors` array naming each bad field. | Fix the request payload and retry. |
| `unauthenticated` | 401 | Authentication Required | No bearer token, an invalid Firebase ID token, or an invalid/expired Coraxis JWT was supplied. | Sign in again (GitHub OAuth or email/password). |
| `forbidden` | 403 | Forbidden | The authenticated account lacks permission for this action (e.g. modifying a built-in agent, accessing another user's resource). | Use an account with sufficient privileges. |
| `not_found` | 404 | Not Found | The requested resource (run, agent, team, credential, etc.) does not exist or is not owned by the caller. | Verify the ID and that you own the resource. |
| `conflict` | 409 | Conflict | The request would create a duplicate (e.g. agent slug already exists, email already registered) or exceed a limit (max custom agents, max teams). | Use a different slug/email, or delete the existing resource first. |
| `rate_limited` | 429 | Too Many Requests | The caller exceeded the per-token/IP request rate limit. Includes `Retry-After` header and `retry_after` in the body. | Wait `Retry-After` seconds, then retry. |
| `quota_exceeded` | 429 | Quota Exceeded | A per-user limit was hit (e.g. concurrent runs cap, runs per hour). | Wait for existing runs to finish, or reduce usage. |
| `configuration_error` | 400 | Configuration Required | The request cannot proceed because required configuration is missing (e.g. no provider API key stored). | Add the missing provider key in Settings. |
| `upstream_error` | 502 | Upstream Provider Error | A third-party dependency (LLM provider, search engine) failed. | Retry later; the issue is on the provider side. |

---

## Response shape

Every error response follows [RFC 7807](https://www.rfc-editor.org/rfc/rfc7807):

```json
{
  "type": "https://github.com/nithincodesx/Coraxis/blob/main/docs/errors.md#<code>",
  "title": "<human-readable title>",
  "status": <HTTP status code>,
  "detail": "<human-readable explanation>",
  "code": "<stable error code>",
  "instance": "/api/v1/<path>",
  "request_id": "<unique request identifier>",
  "hint": "<optional actionable hint>"
}
```

Additional fields may be present depending on the error:

| Error code | Extra fields |
|------------|--------------|
| `validation_error` | `errors`: array of `{field, message, type}` |
| `rate_limited` | `retry_after`: seconds to wait |
| `unauthenticated` | `WWW-Authenticate: Bearer` response header |

---

## Special cases

### HTTP exceptions

Starlette `HTTPException` (e.g. 405 Method Not Allowed) is mapped to an RFC 7807
response with `code: "http_<status>"` and `title` set to the exception detail.

### Unhandled exceptions

Unexpected Python exceptions are logged with a full traceback and returned as
`500 internal_error` with `detail: "An unexpected error occurred. Quote the
request_id when reporting this."`. No implementation details are disclosed.

---

## Headers

| Header | When present | Meaning |
|--------|--------------|---------|
| `Retry-After` | `rate_limited` | Seconds to wait before retrying |
| `WWW-Authenticate: Bearer` | `unauthenticated` | Client should present a bearer token |
| `X-Request-ID` | Every response | Correlates logs to this request |
| `X-Response-Time-ms` | Every response | Request processing time in milliseconds |
