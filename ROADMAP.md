# AI Marketing Department Roadmap — Historical V1 Notice

> **LEGACY / NON-AUTHORITATIVE ROADMAP.** The former contents of this path described an early V1 phase plan and must not be interpreted as the current architecture, current implementation status, current provider configuration, or authorization policy.

## Why this file is retained

The original roadmap is useful forensic history, but several assumptions were superseded by later implementation/hardening, including:

- a permanent `Strategist` identity;
- Creative owning primary copy/content responsibilities;
- phase labels such as “Phase 1 (CURRENT)” long after those phases changed;
- provider/tool examples being read as current defaults;
- an “Autonomous” roadmap label being interpreted as direct permission to publish or mutate spend.

Those assumptions must not override current code/tests or `SOURCE_OF_TRUTH.md`.

## Canonical current invariants

The system currently has exactly five permanent logical agents:

1. CMO
2. Intelligence
3. Content
4. Creative
5. Performance

Final CMO reuses the same CMO identity. Historical `STRATEGIST` / `STRATEGY` values are compatibility/history only and do not create a sixth authority.

Executive strategy and commercial sign-off belong to CMO. Content owns messaging/copy/editorial/channel semantics. Creative owns visual/multimedia production. Performance owns authoritative measurement/attribution and governed performance operations. Intelligence owns evidence/research.

Consequential external actions remain behind current runtime/tool/policy/approval authority. A roadmap or autonomy label cannot grant publishing, spend, credential, or irreversible mutation permission.

Provider/model behavior is defined by current executable model policy/registry/settings. Fallback is explicit; an empty fallback chain means no fallback.

## Historical roadmap archive

The complete pre-migration V1 roadmap remains recoverable from Git history at blob:

`4f51ac5c0d7bba98751246afc54ceee1475e03de`

Use it only for roadmap archaeology and historical implementation context.

## Where to determine current work

For current state and priorities, use this order:

1. exact-head code and tests;
2. `SOURCE_OF_TRUTH.md`;
3. `ARCHITECTURE.md` and `AGENT_PROTOCOL.md`;
4. current Draft PR description / exact-head CI evidence for the active integration workstream;
5. `STATUS_MATRIX.md` as chronological phase evidence, interpreted with the supersession rules in `SOURCE_OF_TRUTH.md`.

Do not infer a new production capability merely because it appeared in the historical V1 roadmap.