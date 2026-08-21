# Creative Engine Architecture (CREATIVE_ENGINE.md)

## 1. Vision & Overview

The **Creative Engine** is a modular, provider-agnostic multimedia synthesis pipeline directed by the **Creative Agent**. It automates the transformation of strategic marketing briefs into high-converting visual and audio assets—ranging from static ad banners to multi-scene short-form video ads (TikTok, Reels, Shorts) and long-form video content.

The system is designed with **zero vendor lock-in**: image generation, video synthesis, voice generation, and video editing are decoupled into standardized abstract adapters.

---

## 2. End-to-End Creative Production Pipeline

```
┌─────────────────┐
│ Research Input  │ (Target Persona, Competitor Hooks, Pain Points)
└────────┬────────┘
         ▼
┌─────────────────┐
│Creative Strategy│ (Core Theme, Emotional Angle, Value Proposition)
└────────┬────────┘
         ▼
┌─────────────────┐
│Creative Concepts│ (Angle Exploration: e.g., "UGC Skeptic", "POV Nightmare")
└────────┬────────┘
         ▼
┌─────────────────┐
│ Hook Generation │ (3-5 Second Hook Variants: Question, Contrarian, Visual Shock)
└────────┬────────┘
         ▼
┌─────────────────┐
│ Scriptwriting   │ (Full Narrative: Hook -> Problem -> Agitation -> Solution -> Proof -> CTA)
└────────┬────────┘
         ▼
┌─────────────────┐
│  Storyboarding  │ (Scene-by-scene breakdown with visual descriptions, camera cues & pacing)
└────────┬────────┘
         ▼
┌─────────────────┐
│    Shot List    │ (Asset Manifest: Prompts, seed references, audio cues, overlays)
└────────┬────────┘
         ▼
┌─────────────────┐
│Asset Generation │ ──┬──> [Image Generation] (Product hero, backdrops, character poses)
│                 │   ├──> [Video Generation] (AI B-roll, talking avatars, dynamic actions)
│                 │   ├──> [Voice Synthesis]  (ElevenLabs/OpenAI TTS/Local Bark)
│                 │   └──> [Music & SFX]      (Background audio, stingers, whooshes)
└────────┬────────┘
         ▼
┌─────────────────┐
│Automated Video  │ (Timeline Assembly, Trims, Speed Ramping, Transitions, Overlays)
│    Editing      │
└────────┬────────┘
         ▼
┌─────────────────┐
│ Subtitles & OST │ (Word-level timed captions, stylized typography, kinetic text)
└────────┬────────┘
         ▼
┌─────────────────┐
│ Thumbnail Synth │ (High-CTR frame capture, sticker overlays, title typography)
└────────┬────────┘
         ▼
┌─────────────────┐
│ Final Rendering │ (FFmpeg / GPU Cloud Renderer: Multi-resolution 9:16, 16:9, 1:1)
└────────┬────────┘
         ▼
┌─────────────────┐
│  Creative QA    │ (Automated checks: Safe-zone compliance, audio normalization, brand colors)
└────────┬────────┘
         ▼
┌─────────────────┐
│   CMO Review    │ (Sign-off on brand consistency and legal compliance)
└────────┬────────┘
         ▼
┌─────────────────┐
│Platform Ready   │ (Handed off to Performance Agent for campaign staging)
└─────────────────┘
```

---

## 3. Modular Adapter Architecture

The Creative Engine relies on abstract base interfaces, allowing seamless swapping between cloud APIs and local inference engines.

```
                         ┌─────────────────────────────┐
                         │   Creative Engine Core      │
                         └──────────────┬──────────────┘
                                        │
      ┌──────────────────┬──────────────┴───────┬──────────────────┐
      │                  │                      │                  │
      ▼                  ▼                      ▼                  ▼
┌─────────────┐   ┌─────────────┐        ┌─────────────┐    ┌─────────────┐
│    Image    │   │    Video    │        │    Audio    │    │    Video    │
│  Generator  │   │  Generator  │        │  Synthesis  │    │   Editor    │
│  Interface  │   │  Interface  │        │  Interface  │    │  Interface  │
└──────┬──────┘   └──────┬──────┘        └──────┬──────┘    └──────┬──────┘
       │                 │                      │                  │
 ┌─────┴─────┐     ┌─────┴─────┐          ┌─────┴─────┐      ┌─────┴─────┐
 │ Midjourney│     │ Runway Gen│          │ ElevenLabs│      │ FFmpeg    │
 │ Flux.1    │     │ Kling AI  │          │ OpenAI TTS│      │ Remotion  │
 │ SDXL      │     │ Luma/Sora │          │ Coqui/Bark│      │ MoviePy   │
 └───────────┘     └───────────┘          └───────────┘      └───────────┘
```

### 3.1 Standard Interface Contracts
- **`ImageGeneratorAdapter`**: `generate_image(prompt, aspect_ratio, style_ref, negative_prompt) -> ImageAsset`
- **`VideoGeneratorAdapter`**: `generate_video(prompt, image_ref, duration_seconds, motion_bucket) -> VideoClip`
- **`VoiceSynthesisAdapter`**: `synthesize_voice(text, voice_id, emotion, speaking_rate) -> AudioAsset`
- **`AudioMusicAdapter`**: `fetch_or_synthesize_bgm(mood, bpm, duration_seconds) -> AudioAsset`
- **`VideoEditorAdapter`**: `assemble_timeline(timeline_manifest: TimelineManifest) -> RenderedVideo`

---

## 4. Video Editing Capabilities Specification

The automated editing subsystem consumes a declarative `TimelineManifest` and executes non-linear editing via headless engines (FFmpeg / Remotion / MoviePy):

```json
{
  "project_id": "EDIT-20260816-01",
  "aspect_ratio": "9:16",
  "fps": 30,
  "canvas": {"width": 1080, "height": 1920},
  "audio_tracks": [
    {
      "track_id": "voiceover",
      "src": "assets/vo_hook_01.wav",
      "start_time": 0.0,
      "volume_db": 0.0,
      "ducking": true
    },
    {
      "track_id": "bgm",
      "src": "assets/bgm_upbeat.mp3",
      "start_time": 0.0,
      "volume_db": -16.0,
      "fade_out": 1.5
    }
  ],
  "video_tracks": [
    {
      "scene_id": "SCN-01",
      "clip_src": "assets/clip_hook.mp4",
      "start_time": 0.0,
      "duration": 2.5,
      "operations": [
        {"type": "reframe", "mode": "center_crop"},
        {"type": "zoom", "start_scale": 1.0, "end_scale": 1.15},
        {"type": "speed", "factor": 1.1}
      ]
    },
    {
      "scene_id": "SCN-02",
      "clip_src": "assets/clip_problem.mp4",
      "start_time": 2.5,
      "duration": 3.0,
      "transition_in": {"type": "jump_cut"}
    }
  ],
  "subtitles": {
    "src": "assets/captions.srt",
    "font": "Proxima Nova Black",
    "font_size": 56,
    "highlight_color": "#FFE500",
    "animation": "word_by_word_pop"
  }
}
```

### Supported Editing Operations:
- **Spatial**: Trim, split, crop, resize, reframe (16:9 to 9:16), dynamic pan, punch-in zooms.
- **Temporal**: Speed ramping, jump cuts, scene pacing adjustment.
- **Compositing**: B-roll cutaways, sticker overlays, lower-thirds, CTA buttons, progress bars.
- **Typography**: Dynamic animated subtitles with word-by-word active karaoke highlights, safe-margin positioning.
- **Audio Engineering**: Voiceover noise suppression, BGM auto-ducking under dialogue, sound effect (SFX) cue alignment, LUFS audio normalization (-14 LUFS for social).
- **Rendering & Packaging**: Multi-format exports with bitrate optimization for Meta, TikTok, and YouTube algorithms.

---

## 5. Closed-Loop Creative Component Attribution

To enable scientific optimization, every rendered asset maintains a cryptographic metadata manifest linking each frame and second to its creative atomic components:

```
[Rendered Video Ad]
  │
  ├── Hook Component        ──> [Hook ID: HOOK-042 (Type: "Contrarian Mythbuster")]
  ├── Visual Angle          ──> [Angle: "Overwhelmed Solo Founder"]
  ├── Narrative Script      ──> [Script ID: SCRIPT-108]
  ├── Scene Breakdown       ──> [Scenes 1..5: durations, pacing, visuals]
  ├── Audio Style           ──> [Voice: "Energetic Creator", BGM: "Tech House"]
  ├── Editing Style         ──> [Style: "Fast-Paced UGC Jumpcuts"]
  └── CTA Style             ──> [CTA: "Free 14-Day Trial"]
```

When the **Performance Agent** reports that `Ad_Variant_A` achieved a 3.4x higher ROAS and 45% lower CPA than `Ad_Variant_B`, the analytics pipeline isolates the differing component (e.g., *Hook-042 vs Hook-011*) and feeds the winning pattern directly into the **Learning System**.
