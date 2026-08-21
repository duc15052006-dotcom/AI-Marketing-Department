"""YouTube Public Observation Backend (yt-dlp Python Adapter).

Provides read-only observation capabilities for public YouTube video metadata and transcripts.
Uses yt-dlp's Python API in skip-download mode, fetches timedtext transcripts via HTTP,
and normalizes all output into typed ObservationRecord schemas.
Zero video/audio media downloads, zero cookies, and zero ffmpeg dependencies.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple
import httpx
import yt_dlp
from tools.gateway.contracts import CostClass, ToolError
from tools.gateway.security import SecurityValidator, SecurityValidationError
from tools.observation.models import (
    CaptionGenerationType,
    ContentTrustLevel,
    ContentTruthStatus,
    EpistemicType,
    ExtractionConfidence,
    ExtractionQualityMetrics,
    ObservationRecord,
    SourceCredibility,
    TranscriptionQuality,
)


class YouTubeYtDlpBackend:
    """Dedicated read-only YouTube metadata and transcript observation backend."""

    BACKEND_ID = "youtube_ytdlp"
    COST_CLASS = CostClass.COST_1_LOCAL_PARSE

    # Regex patterns for supported public YouTube video URLs
    YOUTUBE_WATCH_REGEX = re.compile(
        r"^(https?://)?(www\.|m\.)?youtube\.com/watch\?.*v=([a-zA-Z0-9_-]{11})", re.IGNORECASE
    )
    YOUTUBE_SHORT_REGEX = re.compile(
        r"^(https?://)?youtu\.be/([a-zA-Z0-9_-]{11})", re.IGNORECASE
    )
    YOUTUBE_SHORTS_REGEX = re.compile(
        r"^(https?://)?(www\.)?youtube\.com/shorts/([a-zA-Z0-9_-]{11})", re.IGNORECASE
    )

    UNSUPPORTED_PATTERNS = [
        re.compile(r"youtube\.com/(c|channel|user)/", re.IGNORECASE),
        re.compile(r"youtube\.com/playlist\?", re.IGNORECASE),
        re.compile(r"youtube\.com/results\?", re.IGNORECASE),
    ]

    def __init__(self, default_timeout: float = 15.0) -> None:
        self.default_timeout = default_timeout

    def extract_video_id(self, url: str) -> Tuple[Optional[str], Optional[ToolError]]:
        """Validate and parse video ID from supported public YouTube URL forms."""
        if not url or not isinstance(url, str):
            return None, ToolError(
                error_code="INVALID_YOUTUBE_URL",
                message="Target URL must be a non-empty string.",
                backend_used=self.BACKEND_ID,
            )

        cleaned_url = url.strip()

        for pattern in self.UNSUPPORTED_PATTERNS:
            if pattern.search(cleaned_url):
                return None, ToolError(
                    error_code="UNSUPPORTED_YOUTUBE_RESOURCE",
                    message="Channels, playlists, and search queries are not supported in Phase 3C.1.",
                    backend_used=self.BACKEND_ID,
                    retryable=False,
                )

        match = self.YOUTUBE_WATCH_REGEX.search(cleaned_url)
        if match:
            parsed = urllib.parse.urlparse(cleaned_url)
            query_params = urllib.parse.parse_qs(parsed.query)
            if "v" in query_params and query_params["v"]:
                return query_params["v"][0], None

        match = self.YOUTUBE_SHORT_REGEX.search(cleaned_url)
        if match:
            return match.group(2), None

        match = self.YOUTUBE_SHORTS_REGEX.search(cleaned_url)
        if match:
            return match.group(3), None

        return None, ToolError(
            error_code="INVALID_YOUTUBE_URL",
            message=f"URL '{url}' is not a recognized public YouTube video format.",
            backend_used=self.BACKEND_ID,
            retryable=False,
        )

    def youtube_metadata(
        self,
        url: str,
        product_id: str,
        brand_id: str,
        timeout: Optional[float] = None,
    ) -> Tuple[Optional[ObservationRecord], Optional[ToolError]]:
        """Extract public metadata for a YouTube video using yt-dlp."""
        t0 = time.perf_counter()
        req_timeout = timeout or self.default_timeout

        video_id, err = self.extract_video_id(url)
        if err:
            return None, err

        t_val = time.perf_counter()
        validation_latency_ms = (t_val - t0) * 1000.0

        canonical_url = f"https://www.youtube.com/watch?v={video_id}"
        t_extract_start = time.perf_counter()

        ydl_opts = {
            "skip_download": True,
            "extract_flat": False,
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": req_timeout,
            "no_color": True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_raw = ydl.extract_info(canonical_url, download=False)
                info = ydl.sanitize_info(info_raw)
        except yt_dlp.utils.DownloadError as e:
            msg = str(e)
            if "Private video" in msg:
                return None, ToolError(
                    error_code="VIDEO_PRIVATE",
                    message="Target YouTube video is marked private.",
                    backend_used=self.BACKEND_ID,
                )
            elif "Sign in" in msg or "members-only" in msg:
                return None, ToolError(
                    error_code="AUTH_REQUIRED",
                    message="Target video requires authentication or membership.",
                    backend_used=self.BACKEND_ID,
                )
            elif "Video unavailable" in msg:
                return None, ToolError(
                    error_code="VIDEO_UNAVAILABLE",
                    message="Target YouTube video is unavailable or deleted.",
                    backend_used=self.BACKEND_ID,
                )
            return None, ToolError(
                error_code="BACKEND_EXTRACTION_ERROR",
                message=f"yt-dlp extraction error: {msg}",
                backend_used=self.BACKEND_ID,
            )
        except Exception as e:
            return None, ToolError(
                error_code="BACKEND_EXTRACTION_ERROR",
                message=f"Unexpected extraction failure: {type(e).__name__}: {str(e)}",
                backend_used=self.BACKEND_ID,
            )

        t_extract_end = time.perf_counter()
        backend_extraction_latency_ms = (t_extract_end - t_extract_start) * 1000.0
        total_latency_ms = (t_extract_end - t0) * 1000.0

        if not info:
            return None, ToolError(
                error_code="VIDEO_UNAVAILABLE",
                message="yt-dlp returned empty info dictionary.",
                backend_used=self.BACKEND_ID,
            )

        subtitles_map = info.get("subtitles") or {}
        auto_subtitles_map = info.get("automatic_captions") or {}

        normalized_data = {
            "video_id": info.get("id") or video_id,
            "title": info.get("title"),
            "description": info.get("description"),
            "channel_id": info.get("channel_id"),
            "channel_name": info.get("channel") or info.get("uploader"),
            "upload_date": info.get("upload_date"),
            "duration_seconds": info.get("duration"),
            "webpage_url": info.get("webpage_url") or canonical_url,
            "thumbnail_reference": info.get("thumbnail"),
            "reported_view_count": info.get("view_count"),
            "reported_like_count": info.get("like_count"),
            "reported_comment_count": info.get("comment_count"),
            "availability": info.get("availability"),
            "live_status": info.get("live_status"),
            "subtitle_languages": sorted(list(subtitles_map.keys())),
            "automatic_caption_languages": sorted(list(auto_subtitles_map.keys())),
            "telemetry": {
                "backend_version": yt_dlp.version.__version__,
                "validation_latency_ms": round(validation_latency_ms, 2),
                "backend_extraction_latency_ms": round(backend_extraction_latency_ms, 2),
                "total_latency_ms": round(total_latency_ms, 2),
            },
        }

        has_id = bool(normalized_data["video_id"])
        has_title = bool(normalized_data["title"])
        has_channel = bool(normalized_data["channel_name"])

        if has_id and has_title and has_channel:
            ext_conf = ExtractionConfidence.HIGH
        elif has_id and has_title:
            ext_conf = ExtractionConfidence.MEDIUM
        else:
            ext_conf = ExtractionConfidence.LOW

        obs = ObservationRecord(
            capability="youtube_metadata",
            source_platform="youtube",
            source_type="video",
            source_url_or_id=canonical_url,
            backend_used=self.BACKEND_ID,
            collection_method="YTDLP_PUBLIC_EXTRACTION",
            normalized_data=normalized_data,
            evidence_class=EpistemicType.OBSERVATION,
            extraction_confidence=ext_conf,
            source_credibility=SourceCredibility.UNKNOWN,
            content_truth_status=ContentTruthStatus.UNVERIFIED,
            limitations=[
                "Public metadata observed via yt-dlp Python adapter",
                "Engagement metrics (views, likes, comments) are platform-reported observations, not verified transaction demand",
            ],
            product_id=product_id,
            brand_id=brand_id,
            content_trust=ContentTrustLevel.UNTRUSTED_EXTERNAL,
        )

        return obs, None

    def read_transcript(
        self,
        url: str,
        product_id: str,
        brand_id: str,
        preferred_languages: Optional[List[str]] = None,
        timeout: Optional[float] = None,
    ) -> Tuple[Optional[ObservationRecord], Optional[ToolError]]:
        """Fetch and parse transcript segments for a YouTube video with language selection provenance."""
        t0 = time.perf_counter()
        req_timeout = timeout or self.default_timeout
        prefs = preferred_languages or ["vi", "en"]

        video_id, err = self.extract_video_id(url)
        if err:
            return None, err

        t_val = time.perf_counter()
        validation_latency_ms = (t_val - t0) * 1000.0

        canonical_url = f"https://www.youtube.com/watch?v={video_id}"
        t_extract_start = time.perf_counter()

        ydl_opts = {
            "skip_download": True,
            "extract_flat": False,
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": req_timeout,
            "no_color": True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_raw = ydl.extract_info(canonical_url, download=False)
                info = ydl.sanitize_info(info_raw)
        except Exception as e:
            return None, ToolError(
                error_code="BACKEND_EXTRACTION_ERROR",
                message=f"yt-dlp failed to fetch subtitle metadata: {type(e).__name__}: {str(e)}",
                backend_used=self.BACKEND_ID,
            )

        t_extract_end = time.perf_counter()
        backend_extraction_latency_ms = (t_extract_end - t_extract_start) * 1000.0

        if not info:
            return None, ToolError(
                error_code="VIDEO_UNAVAILABLE",
                message="yt-dlp returned empty video info.",
                backend_used=self.BACKEND_ID,
            )

        subtitles = info.get("subtitles") or {}
        auto_subtitles = info.get("automatic_captions") or {}

        available_manual = sorted(list(subtitles.keys()))
        available_auto = sorted(list(auto_subtitles.keys()))

        # 3. Deterministic Language Selection with Explicit Provenance
        chosen_lang: Optional[str] = None
        chosen_track_type: Optional[str] = None  # MANUAL_SUBTITLES | AUTOMATIC_CAPTIONS
        selection_reason: Optional[str] = None
        chosen_formats: Optional[List[Dict[str, Any]]] = None

        # A. Preferred Manual
        for lang in prefs:
            if lang in subtitles and subtitles[lang]:
                chosen_lang = lang
                chosen_track_type = "MANUAL_SUBTITLES"
                selection_reason = "PREFERRED_MANUAL"
                chosen_formats = subtitles[lang]
                break

        # B. Preferred Automatic
        if not chosen_lang:
            for lang in prefs:
                if lang in auto_subtitles and auto_subtitles[lang]:
                    chosen_lang = lang
                    chosen_track_type = "AUTOMATIC_CAPTIONS"
                    selection_reason = "PREFERRED_AUTOMATIC"
                    chosen_formats = auto_subtitles[lang]
                    break

        # C. Any Manual
        if not chosen_lang and subtitles:
            first_lang = next(iter(subtitles.keys()))
            chosen_lang = first_lang
            chosen_track_type = "MANUAL_SUBTITLES"
            selection_reason = "FIRST_AVAILABLE_FALLBACK"
            chosen_formats = subtitles[first_lang]

        # D. Any Automatic
        if not chosen_lang and auto_subtitles:
            first_lang = next(iter(auto_subtitles.keys()))
            chosen_lang = first_lang
            chosen_track_type = "AUTOMATIC_CAPTIONS"
            selection_reason = "FIRST_AVAILABLE_FALLBACK"
            chosen_formats = auto_subtitles[first_lang]

        if not chosen_lang or not chosen_formats:
            return None, ToolError(
                error_code="TRANSCRIPT_NOT_AVAILABLE",
                message=f"No manual subtitles or automatic captions available for video '{video_id}'.",
                backend_used=self.BACKEND_ID,
            )

        # 4. Fetch Subtitle Payload (prefer 'json3', fallback to 'srv1'/'vtt')
        sub_url = None
        for fmt in chosen_formats:
            if fmt.get("ext") == "json3" and fmt.get("url"):
                sub_url = fmt["url"]
                break
        if not sub_url and chosen_formats:
            sub_url = chosen_formats[0].get("url")

        if not sub_url:
            return None, ToolError(
                error_code="TRANSCRIPT_FORMAT_UNAVAILABLE",
                message=f"No accessible transcript stream URL found for language '{chosen_lang}'.",
                backend_used=self.BACKEND_ID,
            )

        t_parse_start = time.perf_counter()
        segments: List[Dict[str, Any]] = []

        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            with httpx.Client(timeout=req_timeout) as client:
                resp = client.get(sub_url, headers=headers)
                if resp.status_code == 200:
                    try:
                        timedtext_data = resp.json()
                        events = timedtext_data.get("events", [])
                        for ev in events:
                            if "segs" in ev:
                                seg_text = "".join(s.get("utf8", "") for s in ev.get("segs", [])).strip()
                                if seg_text:
                                    segments.append({
                                        "start_seconds": round(ev.get("tStartMs", 0) / 1000.0, 3),
                                        "duration_seconds": round(ev.get("dDurationMs", 0) / 1000.0, 3),
                                        "text": seg_text,
                                    })
                    except Exception:
                        lines = [line.strip() for line in resp.text.splitlines() if line.strip()]
                        if lines:
                            segments.append({
                                "start_seconds": 0.0,
                                "duration_seconds": float(info.get("duration") or 0.0),
                                "text": " ".join(lines[:100]),
                            })
        except Exception as e:
            return None, ToolError(
                error_code="TRANSCRIPT_DOWNLOAD_ERROR",
                message=f"Failed to fetch transcript stream: {str(e)}",
                backend_used=self.BACKEND_ID,
            )

        t_parse_end = time.perf_counter()
        transcript_parse_latency_ms = (t_parse_end - t_parse_start) * 1000.0
        total_latency_ms = (t_parse_end - t0) * 1000.0

        if not segments:
            return None, ToolError(
                error_code="TRANSCRIPT_EMPTY",
                message=f"Transcript track '{chosen_lang}' contained zero readable text segments.",
                backend_used=self.BACKEND_ID,
            )

        # 5. Extraction Confidence vs Caption Generation Type vs Transcription Quality
        # Mechanical extraction confidence is HIGH when segments are retrieved
        ext_conf = ExtractionConfidence.HIGH if len(segments) > 0 else ExtractionConfidence.LOW

        gen_type = (
            CaptionGenerationType.MANUAL
            if chosen_track_type == "MANUAL_SUBTITLES"
            else CaptionGenerationType.AUTOMATIC
        )

        normalized_data = {
            "video_id": video_id,
            "title": info.get("title"),
            "language": chosen_lang,
            "language_code": chosen_lang,
            "transcript_type": chosen_track_type,
            "caption_generation_type": gen_type.value,
            "transcription_quality": TranscriptionQuality.UNKNOWN.value,
            "selection_reason": selection_reason,
            "available_manual_languages": available_manual,
            "available_automatic_languages": available_auto,
            "segment_count": len(segments),
            "segments": segments,
            "telemetry": {
                "backend_version": yt_dlp.version.__version__,
                "validation_latency_ms": round(validation_latency_ms, 2),
                "backend_extraction_latency_ms": round(backend_extraction_latency_ms, 2),
                "transcript_parse_latency_ms": round(transcript_parse_latency_ms, 2),
                "total_latency_ms": round(total_latency_ms, 2),
            },
        }

        obs = ObservationRecord(
            capability="read_transcript",
            source_platform="youtube",
            source_type="transcript",
            source_url_or_id=canonical_url,
            backend_used=self.BACKEND_ID,
            collection_method="YTDLP_PUBLIC_EXTRACTION",
            normalized_data=normalized_data,
            evidence_class=EpistemicType.OBSERVATION,
            extraction_confidence=ext_conf,
            source_credibility=SourceCredibility.UNKNOWN,
            content_truth_status=ContentTruthStatus.UNVERIFIED,
            limitations=[
                f"Transcript track type: {chosen_track_type} ({chosen_lang}) selected via {selection_reason}",
                "Spoken assertions in transcript reflect external untrusted speaker claims, not verified objective truth",
            ],
            product_id=product_id,
            brand_id=brand_id,
            content_trust=ContentTrustLevel.UNTRUSTED_EXTERNAL,
        )

        return obs, None
