"""Deterministic Unit Tests for YouTube Observation & yt-dlp Backend (Phase 3C.1).

Validates URL normalization, metadata extraction, manual vs auto subtitle resolution,
language selection priority, missing metrics handling, error normalization,
product isolation, and epistemic boundaries without live internet calls.
"""

import unittest
from unittest.mock import MagicMock, patch
import yt_dlp
from tools.gateway.contracts import (
    CapabilityRequest,
    CapabilityResult,
    CostClass,
    ToolExecutionContext,
)
from tools.gateway.gateway import ToolGateway
from tools.observation.models import (
    ContentTrustLevel,
    ContentTruthStatus,
    EpistemicType,
    ExtractionConfidence,
    ObservationRecord,
    SourceCredibility,
)
from tools.observation.registry import CapabilityRegistry
from tools.observation.router import ObservationRouter
from tools.observation.youtube_backend import YouTubeYtDlpBackend


class TestYouTubeObservation(unittest.TestCase):
    def setUp(self):
        self.registry = CapabilityRegistry()
        self.youtube_backend = YouTubeYtDlpBackend()
        self.gateway = ToolGateway(registry=self.registry, youtube_backend=self.youtube_backend)
        self.router = ObservationRouter(gateway=self.gateway)

    # -------------------------------------------------------------
    # 1. URL Parsing & Normalization Tests
    # -------------------------------------------------------------
    def test_valid_youtube_url_forms_extract_video_id(self):
        """Verify standard watch, short youtu.be, and shorts URLs resolve to 11-char video ID."""
        test_cases = [
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://m.youtube.com/watch?v=dQw4w9WgXcQ&t=10s", "dQw4w9WgXcQ"),
            ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("http://www.youtube.com/watch?v=1234567890a", "1234567890a"),
        ]
        for url, expected_id in test_cases:
            vid, err = self.youtube_backend.extract_video_id(url)
            self.assertIsNone(err)
            self.assertEqual(vid, expected_id)

    def test_unsupported_youtube_resource_types_rejected(self):
        """Verify channels, playlists, and search queries are rejected with UNSUPPORTED_YOUTUBE_RESOURCE."""
        unsupported_urls = [
            "https://www.youtube.com/c/Veritasium",
            "https://www.youtube.com/channel/UC1234567890",
            "https://www.youtube.com/user/TEDtalksDirector",
            "https://www.youtube.com/playlist?list=PL1234567890",
            "https://www.youtube.com/results?search_query=marketing",
        ]
        for url in unsupported_urls:
            vid, err = self.youtube_backend.extract_video_id(url)
            self.assertIsNone(vid)
            self.assertIsNotNone(err)
            self.assertEqual(err.error_code, "UNSUPPORTED_YOUTUBE_RESOURCE")

    def test_invalid_youtube_urls_rejected(self):
        """Verify non-YouTube URLs or malformed URLs return INVALID_YOUTUBE_URL."""
        for invalid_url in [
            "https://example.com/video.mp4",
            "https://youtube.com/about",
            "not_a_url",
            "",
        ]:
            vid, err = self.youtube_backend.extract_video_id(invalid_url)
            self.assertIsNone(vid)
            self.assertIsNotNone(err)
            self.assertIn(err.error_code, ["INVALID_YOUTUBE_URL", "UNSUPPORTED_YOUTUBE_RESOURCE"])

    # -------------------------------------------------------------
    # 2. Metadata Normalization & Missing Metrics Handling
    # -------------------------------------------------------------
    @patch.object(yt_dlp.YoutubeDL, "extract_info")
    def test_youtube_metadata_normalization_and_epistemic_safety(self, mock_extract):
        """Verify metadata fields map correctly and engagement metrics are treated as platform observations."""
        mock_raw_info = {
            "id": "dQw4w9WgXcQ",
            "title": "Rick Astley - Never Gonna Give You Up (Official Music Video)",
            "description": "The official video for Never Gonna Give You Up by Rick Astley",
            "channel_id": "UCuAXFkgsw1L7xaCfnd5JJOw",
            "channel": "Rick Astley",
            "upload_date": "20091025",
            "duration": 213,
            "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
            "view_count": 1500000000,
            "like_count": 17000000,
            "comment_count": None,  # Missing/disabled comments
            "availability": "public",
            "live_status": "not_live",
            "subtitles": {"en": [{"ext": "vtt"}]},
            "automatic_captions": {"en": [{"ext": "srv1"}]},
        }
        mock_extract.return_value = mock_raw_info

        res: CapabilityResult = self.router.youtube_metadata(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            product_id="PROD_TEST_YT",
            brand_id="BRAND_TEST",
        )

        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.backend_used, "youtube_ytdlp")
        self.assertEqual(res.cost_class, CostClass.COST_1_LOCAL_PARSE)

        obs = ObservationRecord(**res.observation_record)
        data = obs.normalized_data

        self.assertEqual(data["video_id"], "dQw4w9WgXcQ")
        self.assertEqual(data["title"], "Rick Astley - Never Gonna Give You Up (Official Music Video)")
        self.assertEqual(data["channel_name"], "Rick Astley")
        self.assertEqual(data["reported_view_count"], 1500000000)
        self.assertEqual(data["reported_like_count"], 17000000)
        # Invariant: missing metric is None/null, NOT converted to 0
        self.assertIsNone(data["reported_comment_count"])

        # Epistemic boundaries
        self.assertEqual(obs.evidence_class, EpistemicType.OBSERVATION)
        self.assertEqual(obs.source_credibility, SourceCredibility.UNKNOWN)
        self.assertEqual(obs.content_truth_status, ContentTruthStatus.UNVERIFIED)
        self.assertEqual(obs.extraction_confidence, ExtractionConfidence.HIGH)
        self.assertEqual(obs.content_trust, ContentTrustLevel.UNTRUSTED_EXTERNAL)
        self.assertEqual(obs.product_id, "PROD_TEST_YT")
        self.assertEqual(obs.brand_id, "BRAND_TEST")

    # -------------------------------------------------------------
    # 3. Transcript Extraction, Language Selection & Priority Tests
    # -------------------------------------------------------------
    @patch("httpx.Client.get")
    @patch.object(yt_dlp.YoutubeDL, "extract_info")
    def test_transcript_manual_subtitle_priority_selection(self, mock_extract, mock_http_get):
        """Verify preferred manual subtitles are selected before automatic captions."""
        mock_raw_info = {
            "id": "test_video_123",
            "title": "Tutorial Video",
            "duration": 60,
            "subtitles": {
                "en": [{"ext": "json3", "url": "https://subtitles.youtube.com/en_manual.json3"}],
                "fr": [{"ext": "json3", "url": "https://subtitles.youtube.com/fr_manual.json3"}],
            },
            "automatic_captions": {
                "en": [{"ext": "json3", "url": "https://subtitles.youtube.com/en_auto.json3"}],
            },
        }
        mock_extract.return_value = mock_raw_info

        # Mock JSON3 response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "events": [
                {"tStartMs": 0, "dDurationMs": 2000, "segs": [{"utf8": "Hello and welcome"}]},
                {"tStartMs": 2500, "dDurationMs": 3000, "segs": [{"utf8": "to this tutorial"}]},
            ]
        }
        mock_http_get.return_value = mock_resp

        res = self.router.read_transcript(
            url="https://www.youtube.com/watch?v=test_video_123",
            product_id="PROD_TEST_YT",
            brand_id="BRAND_TEST",
            preferred_languages=["en"],
        )

        self.assertEqual(res.status, "SUCCESS")
        obs = ObservationRecord(**res.observation_record)
        data = obs.normalized_data

        self.assertEqual(data["language"], "en")
        self.assertEqual(data["transcript_type"], "MANUAL_SUBTITLES")
        self.assertEqual(data["segment_count"], 2)
        self.assertEqual(data["segments"][0]["text"], "Hello and welcome")
        self.assertEqual(data["segments"][0]["start_seconds"], 0.0)
        self.assertEqual(data["segments"][1]["text"], "to this tutorial")
        self.assertEqual(obs.extraction_confidence, ExtractionConfidence.HIGH)

    @patch("httpx.Client.get")
    @patch.object(yt_dlp.YoutubeDL, "extract_info")
    def test_transcript_automatic_caption_fallback(self, mock_extract, mock_http_get):
        """Verify automatic captions are used when manual subtitles are unavailable."""
        mock_raw_info = {
            "id": "auto_video_456",
            "title": "Unscripted Vlog",
            "duration": 120,
            "subtitles": {},  # No manual subtitles
            "automatic_captions": {
                "en": [{"ext": "json3", "url": "https://subtitles.youtube.com/en_auto.json3"}],
            },
        }
        mock_extract.return_value = mock_raw_info

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "events": [
                {"tStartMs": 1000, "dDurationMs": 1500, "segs": [{"utf8": "automatic speech text"}]}
            ]
        }
        mock_http_get.return_value = mock_resp

        res = self.router.read_transcript(
            url="https://www.youtube.com/watch?v=auto_video_456",
            product_id="PROD_TEST_YT",
            brand_id="BRAND_TEST",
            preferred_languages=["en"],
        )

        self.assertEqual(res.status, "SUCCESS")
        obs = ObservationRecord(**res.observation_record)
        self.assertEqual(obs.normalized_data["transcript_type"], "AUTOMATIC_CAPTIONS")
        self.assertEqual(obs.normalized_data["caption_generation_type"], "AUTOMATIC")
        self.assertEqual(obs.extraction_confidence, ExtractionConfidence.HIGH)

    # -------------------------------------------------------------
    # 4. Error Handling & Edge Cases
    # -------------------------------------------------------------
    @patch.object(yt_dlp.YoutubeDL, "extract_info")
    def test_private_video_error_normalization(self, mock_extract):
        """Verify private video raises VIDEO_PRIVATE normalized error."""
        mock_extract.side_effect = yt_dlp.utils.DownloadError("ERROR: [youtube] 123: Private video")

        res = self.router.youtube_metadata(
            url="https://www.youtube.com/watch?v=1234567890a",
            product_id="PROD_TEST_YT",
            brand_id="BRAND_TEST",
        )
        self.assertEqual(res.status, "ERROR")
        self.assertEqual(res.error.error_code, "VIDEO_PRIVATE")

    @patch.object(yt_dlp.YoutubeDL, "extract_info")
    def test_auth_required_error_normalization(self, mock_extract):
        """Verify sign-in/membership requirement raises AUTH_REQUIRED error."""
        mock_extract.side_effect = yt_dlp.utils.DownloadError("ERROR: [youtube] 123: Sign in to confirm your age")

        res = self.router.youtube_metadata(
            url="https://www.youtube.com/watch?v=1234567890a",
            product_id="PROD_TEST_YT",
            brand_id="BRAND_TEST",
        )
        self.assertEqual(res.status, "ERROR")
        self.assertEqual(res.error.error_code, "AUTH_REQUIRED")

    @patch.object(yt_dlp.YoutubeDL, "extract_info")
    def test_transcript_not_available_error(self, mock_extract):
        """Verify video with no captions returns TRANSCRIPT_NOT_AVAILABLE."""
        mock_raw_info = {
            "id": "silent_video_789",
            "title": "Silent Animation",
            "subtitles": {},
            "automatic_captions": {},
        }
        mock_extract.return_value = mock_raw_info

        res = self.router.read_transcript(
            url="https://www.youtube.com/watch?v=silent_video_789",
            product_id="PROD_TEST_YT",
            brand_id="BRAND_TEST",
        )
        self.assertEqual(res.status, "ERROR")
        self.assertEqual(res.error.error_code, "TRANSCRIPT_NOT_AVAILABLE")


if __name__ == "__main__":
    unittest.main()
