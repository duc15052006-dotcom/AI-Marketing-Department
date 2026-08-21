"""Creative Engine Schemas.

Declarative schemas for video timeline assembly, shot lists, audio mixing,
and automated editing operations.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from schemas.base import BaseModel, Field


class EditingOperation(BaseModel):
    """Atomic editing operation applied to a visual track."""
    type: Literal["trim", "split", "crop", "resize", "reframe", "speed", "zoom", "jump_cut", "fade", "overlay"]
    params: Dict[str, Any] = Field(default_factory=dict)


class AudioTrack(BaseModel):
    """Audio stream specification (voiceover, BGM, SFX)."""
    track_id: str
    track_type: Literal["voiceover", "bgm", "sfx"] = Field(default="voiceover")
    src: str = Field(default="")
    start_time: float = Field(default=0.0)
    duration: Optional[float] = None
    volume_db: float = Field(default=0.0)
    ducking: bool = Field(default=False)
    fade_in: float = Field(default=0.0)
    fade_out: float = Field(default=0.0)


class VideoTrackClip(BaseModel):
    """Video clip placement on the master editing timeline."""
    scene_id: str
    clip_src: str
    start_time: float
    duration: float
    operations: List[EditingOperation] = Field(default_factory=list)
    transition_in: Optional[Dict[str, Any]] = None
    transition_out: Optional[Dict[str, Any]] = None


class SubtitleConfig(BaseModel):
    """Automated typography and karaoke subtitle specification."""
    src: str = Field(..., description="SRT / VTT / JSON word-timestamped caption path")
    font_family: str = Field(default="Inter")
    font_size: int = Field(default=52)
    primary_color: str = Field(default="#FFFFFF")
    highlight_color: str = Field(default="#FFE500")
    animation_style: Literal["none", "word_by_word_pop", "fade_line", "bounce"] = Field(default="word_by_word_pop")
    safe_zone_margin_bottom: int = Field(default=180)


class TimelineManifest(BaseModel):
    """Master non-linear editing timeline passed to the rendering engine."""
    project_id: str
    aspect_ratio: Literal["9:16", "16:9", "1:1", "4:5"] = Field(default="9:16")
    fps: int = Field(default=30)
    width: int = Field(default=1080)
    height: int = Field(default=1920)
    audio_tracks: List[AudioTrack] = Field(default_factory=list)
    video_tracks: List[VideoTrackClip] = Field(default_factory=list)
    subtitles: Optional[SubtitleConfig] = None
    output_format: Literal["mp4", "webm", "mov"] = Field(default="mp4")
    audio_lufs_target: float = Field(default=-14.0)
