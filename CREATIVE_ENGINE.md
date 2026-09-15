# Creative Engine Architecture

## 1. Purpose and canonical boundary

The **Creative Engine** is the provider-neutral multimedia production layer used by the canonical **Creative** ASI. It transforms an approved, evidence-grounded semantic brief into visual, image, video, audio, storyboard, shot-list, editing, and rendered-media artifacts.

The Creative Engine does **not** replace the Content ASI.

Canonical ownership is:

- **CMO** — executive strategy, positioning, GTM choices, commercial trade-offs, final commercial governance.
- **Intelligence** — evidence acquisition, freshness verification, customer/market/competitor research, explicit knowledge gaps.
- **Content** — message architecture, hooks, copy, scripts, CTA wording, editorial/SEO/channel semantics, and the semantic brief sent to Creative.
- **Creative** — visual/multimedia concept, art direction, storyboard, shot list, production specifications, image/video/audio generation, editing, rendering, and media QA.
- **Performance** — measurement, attribution, observed outcome analysis, experiment evidence, and governed performance operations.

There is no permanent Strategist identity and no sixth agent. A Creative tool or adapter never grants publishing, spend, credential, or other consequential external authority by itself.

---

## 2. Required Creative input contract

Before production, Creative should receive a grounded semantic brief from Content, derived from CMO-approved strategy and verified evidence. Material inputs include, when applicable:

- business/content objective;
- product/business/workspace identity;
- target audience and funnel/customer state;
- CMO-approved positioning and offer guardrails;
- verified message hierarchy;
- approved hook/copy/script/CTA text or clearly marked semantic placeholders;
- required proof/evidence and factual constraints;
- brand visual/verbal constraints;
- channel, format, aspect ratio, duration, and placement requirements;
- prohibited claims or mandatory exclusions;
- experiment/variant identity and measurement question;
- known unknowns that Creative must not invent.

If a material semantic input is missing, Creative may request clarification/revision from Content or CMO as appropriate. It must not silently manufacture product facts, positioning, customer evidence, pricing, guarantees, or performance claims.

---

## 3. Canonical production pipeline

```text
CMO-approved strategy + Intelligence evidence
                    ↓
        CONTENT SEMANTIC BRIEF
  message / hook / copy / script / CTA
  evidence + factual constraints + format
                    ↓
              CREATIVE ASI
                    ↓
        Visual / Multimedia Concept
                    ↓
             Storyboard / Shot List
                    ↓
       Production Manifest / Prompts
                    ↓
      Image / Video / Audio Generation
                    ↓
        Editing / Compositing / Timing
                    ↓
       Subtitles / Graphics / Packaging
                    ↓
             Render / Media QA
                    ↓
       Creative production artifacts
                    ↓
              PERFORMANCE
  measurement / attribution / experiment evidence
                    ↓
            FINAL CMO GOVERNANCE
```

### 3.1 What Creative may adapt

Creative may make **production-level** adaptations needed to express the approved semantic brief in media, for example:

- visual metaphor, composition, art direction, lighting, camera language, pacing, transitions;
- scene allocation and shot order;
- subtitle timing/layout and on-screen typography;
- voice performance direction, music/SFX choices, edit rhythm;
- aspect-ratio and placement-specific visual adaptation;
- non-semantic timing edits that preserve approved meaning.

If a production constraint requires changing the **meaning** of a claim, hook, script, CTA, positioning, or factual promise, Creative must return the issue to Content/CMO rather than silently rewriting semantic authority.

---

## 4. Provider-neutral adapter architecture

The engine should depend on capability contracts rather than permanent agent logic tied to one vendor.

Conceptual interfaces may include:

- `ImageGeneratorAdapter`
- `VideoGeneratorAdapter`
- `VoiceSynthesisAdapter`
- `AudioMusicAdapter`
- `VideoEditorAdapter`
- rendering/packaging adapters

Illustrative providers or engines such as Flux, SDXL, Kling, Runway, FFmpeg, Remotion, MoviePy, ElevenLabs, OpenAI-compatible services, or local models are **examples only**. Their presence in documentation does not mean they are installed, enabled, configured, free, approved, or selected for the current run.

Actual provider/tool selection must be resolved through current provider/capability/tool configuration and policy. Secrets must remain behind safe credential references/settings, and an unavailable adapter must not be replaced by an implicit unauthorized provider fallback.

---

## 5. Production manifests and reproducibility

A production manifest should preserve enough structured information to reproduce or audit the intended media operation where the active tools support it. Typical fields may include:

- run/task/product/brand identity;
- source semantic brief / content artifact ID;
- visual concept ID;
- storyboard/scene/shot IDs;
- aspect ratio, resolution, frame rate, duration;
- prompt/specification inputs and negative constraints;
- referenced assets;
- provider/model/tool identity where material;
- seed or deterministic parameters when a provider exposes them;
- edit/timeline instructions;
- output artifact IDs/paths/hashes where actually produced by the implementation;
- warnings, unsupported capabilities, and failed/ambiguous tool results.

Do not call metadata “cryptographic,” “immutable,” or “reproducible” unless the exact implementation and test evidence establish that property for the artifact in question.

---

## 6. Video and multimedia assembly

A declarative timeline may describe operations such as:

- trim, split, crop, resize, reframe, pan, zoom;
- scene timing and speed changes;
- B-roll, overlays, lower-thirds, CTA graphics, progress indicators;
- subtitle timing/layout and on-screen text;
- voiceover, BGM, SFX alignment and ducking;
- audio-level normalization where supported;
- multi-format exports and encoding/packaging.

These are capabilities, not promises. The runtime/tool gateway must truthfully report whether a requested operation is actually supported by the selected adapter.

Example conceptual timeline fragment:

```json
{
  "aspect_ratio": "9:16",
  "fps": 30,
  "scenes": [
    {
      "scene_id": "SCN-01",
      "duration_seconds": 2.5,
      "visual_spec": "product close-up with approved visual direction",
      "voiceover_source": "CONTENT_SCRIPT_SEGMENT_01"
    }
  ],
  "semantic_source": {
    "hook_id": "HOOK-042",
    "script_id": "SCRIPT-108",
    "cta_id": "CTA-014"
  }
}
```

The hook/script/CTA identifiers point back to Content-owned semantic artifacts; Creative owns how those semantics are rendered into media.

---

## 7. Creative QA

Creative QA should validate only properties it can actually observe or deterministically check, such as applicable:

- requested aspect ratio/resolution/duration;
- missing or corrupt assets;
- scene/timeline continuity;
- subtitle/overlay bounds;
- required brand visual constraints;
- required product/logo/reference visibility;
- unsupported or failed adapter operations;
- preservation of mandatory semantic text/claims supplied by Content;
- production artifacts and provenance references.

Creative QA must not self-certify legal compliance, product truth, conversion lift, ROAS, or campaign success unless the relevant canonical authority/evidence exists.

---

## 8. Component-level provenance and measurement handoff

Media artifacts should retain structured links between the produced asset and the inputs that matter for later analysis, for example:

```text
Rendered / Produced Asset
  ├── Content hook ID
  ├── Content script / CTA ID
  ├── Creative visual concept ID
  ├── Storyboard / scene / shot IDs
  ├── production tool/provider metadata when available
  ├── editing / audio / visual treatment metadata
  └── product / run / experiment identity
```

Performance may later associate observed results with these component IDs, but correlation is not automatically causal proof. Performance owns authoritative measurement/attribution; causal conclusions must obey the current experiment/evidence policy.

Creative must not rewrite a winning/losing pattern into permanent organizational truth by itself.

---

## 9. Governed execution boundary

Producing a media file does not mean it was published or used in a live campaign.

Any consequential external action must follow the current governed path:

```text
semantic/action intent
      ↓
governed runtime
      ↓
tool/capability policy
      ↓
permission / approval when required
      ↓
external adapter
      ↓
truthful receipt or ambiguous-outcome record
```

Creative has no direct authority to bypass this path.

---

## 10. Fail-closed architecture invariants

A Creative Engine change fails review if it:

- moves primary hook/copy/script/CTA semantic ownership from Content into Creative;
- restores Strategist as an independent permanent authority;
- invents product/customer/market facts to fill a production gap;
- treats provider/tool examples as configured defaults;
- hard-codes a vendor dependency into permanent Creative logic;
- silently performs provider fallback without explicit current policy;
- claims unsupported media generation/rendering capability;
- claims “cryptographic,” “immutable,” or successful external execution without implementation evidence;
- lets Creative self-certify campaign performance or causal learning;
- allows produced media to bypass governed publishing/spend/approval controls.

Current executable code/tests, `SOURCE_OF_TRUTH.md`, `ARCHITECTURE.md`, and `AGENT_PROTOCOL.md` are authoritative over historical Creative Engine descriptions.