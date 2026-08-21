# Tool Security & Legitimate Observation Policy (TOOL_SECURITY_POLICY.md)

**Status**: MANDATORY SECURITY GOVERNANCE & POLICY SPECIFICATION — PHASE 3B.1  
**Scope**: Tool Gateway Security Gates, Sandboxing, Forbidden Upstream Capabilities

---

## 1. Zero Anti-Detection & Legitimate Use Policy

The AI Marketing Department strictly adheres to ethical observation and authorized operational standards. The presence of an anti-detection or stealth feature in an upstream open-source tool does **NOT** make it an authorized capability of our Tool Gateway.

### Explicitly Disallowed Upstream Capabilities

```text
┌─────────────────────────────────────────────────────────────┐
│             DISALLOWED UPSTREAM CAPABILITIES                │
├─────────────────────────────────────────────────────────────┤
│ 1. CAPTCHA_BYPASS          (No automated CAPTCHA solvers)   │
│ 2. FINGERPRINT_EVASION     (No canvas/webGL spoofing)       │
│ 3. STEALTH_BYPASS          (No stealth driver evasion)      │
│ 4. BAN_AVOIDANCE           (No IP rotating for abuse)       │
│ 5. RATE_LIMIT_CIRCUMVENTION(No header spoofing to exceed)   │
│ 6. AUTOMATED_MEDIA_BUYING  (No unauthorized financial spend)│
│ 7. UNAUTHORIZED_CREDENTIALS(No scraping private accounts)   │
└─────────────────────────────────────────────────────────────┘
```

**Policy Enforcement**:
- If an upstream tool (e.g. Browser Use, Agent-Reach) offers flags for CAPTCHA solving or fingerprint manipulation, our Tool Gateway adapters explicitly **hardcode these flags to disabled / inactive**.
- If a target endpoint returns HTTP 403 / 429 or requires a CAPTCHA challenge, the gateway halts execution and reports `STATUS = BLOCKED_TARGET_CHALLENGE` or `RATE_LIMITED`. It does not attempt evasion.

---

## 2. Least Privilege & Tool Sandboxing

External observation tools must never receive unconstrained workspace access:

```text
┌────────────────────────────────────────────────────────────────────────┐
│                   TOOL GATEWAY LEAST-PRIVILEGE MATRIX                  │
├───────────────────┬──────────────────────┬─────────────────────────────┤
│ TOOL / ADAPTER    │ ALLOWED INPUT DATA   │ ALLOWED ACTIONS             │
├───────────────────┼──────────────────────┼─────────────────────────────┤
│ Direct HTTP / BS4 │ Target URL           │ Read-only HTTP GET          │
│ Trafilatura       │ Raw HTML text        │ In-memory text parsing      │
│ yt-dlp            │ Public video URL/ID  │ Metadata & subtitle dump    │
│ Playwright        │ Target URL, selectors│ Read-only DOM snapshot/screencap│
│ Apify MCP         │ Search keywords, URLs│ Read-only cloud dataset pull│
│ Browser Use       │ Target goal & URL    │ Read-only interactive click │
└───────────────────┴──────────────────────┴─────────────────────────────┘
```

---

## 3. Secret Isolation & Zero Leakage

1. **Zero Secret Exposition**: API tokens (e.g. `APIFY_TOKEN`, `BRAVE_API_KEY`) exist only in memory within the `ToolGateway` configuration.
2. **No TaskEnvelope Secret Storage**: Secrets are never placed into `TaskEnvelope`, `AgentRunResult`, `CollaborationTrace`, or `ObservationRecord`.
3. **Redacted Error Traces**: All HTTP error bodies returned by upstream tools are scrubbed of Authorization headers, Bearer tokens, and query parameter keys before recording.

---

## 4. Legitimate Media Ingestion vs. Copyright Protection

When using `yt-dlp` or media download capabilities:
- **Legitimate Ingestion**: Capturing creator audio tracks, subtitles, video duration, and engagement metadata strictly for internal AI semantic analysis, market research, and brief generation.
- **Strictly Prohibited**: Automatic re-uploading, re-broadcasting, or unauthorized commercial distribution of copyrighted third-party media.
