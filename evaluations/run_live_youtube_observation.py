"""Live YouTube Observation Runner (Non-LLM).

Executes real public YouTube observations using ObservationRouter and YouTubeYtDlpBackend.
Tests public metadata, manual subtitles, and automatic captions without downloading media files.
Writes sanitized evaluation artifacts to evaluations/live/observation/youtube/.
"""

import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.observation.router import ObservationRouter


def run_live_youtube_observation():
    print("==================================================")
    print("PHASE 3C.1: LIVE YOUTUBE OBSERVATION VALIDATION (NON-LLM)")
    print("==================================================")

    out_dir = Path(__file__).resolve().parent / "live" / "observation" / "youtube"
    out_dir.mkdir(parents=True, exist_ok=True)

    router = ObservationRouter()

    # Target 1: Public Video for Metadata (Rick Astley - Never Gonna Give You Up)
    url_1 = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    print(f"\n[Test 1] youtube_metadata() on: {url_1}")
    res_1 = router.youtube_metadata(
        url=url_1,
        product_id="PROD_TEST_YT_01",
        brand_id="BRAND_TEST",
    )
    print(f"Status: {res_1.status}, Latency: {res_1.latency_ms:.2f}ms")
    if res_1.status == "SUCCESS":
        obs_1 = res_1.observation_record
        print(f"Title: {obs_1['normalized_data'].get('title')}")
        print(f"Channel: {obs_1['normalized_data'].get('channel_name')}")
        print(f"Reported Views: {obs_1['normalized_data'].get('reported_view_count')}")
        print(f"Reported Likes: {obs_1['normalized_data'].get('reported_like_count')}")
        (out_dir / "youtube_metadata_001.json").write_text(json.dumps(obs_1, indent=2), encoding="utf-8")

    # Target 2: Public Video with Manual Subtitles (YouTube First Video - Me at the zoo)
    url_2 = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    print(f"\n[Test 2] read_transcript() (Manual Subtitles) on: {url_2}")
    res_2 = router.read_transcript(
        url=url_2,
        product_id="PROD_TEST_YT_01",
        brand_id="BRAND_TEST",
        preferred_languages=["en"],
    )
    print(f"Status: {res_2.status}, Latency: {res_2.latency_ms:.2f}ms")
    if res_2.status == "SUCCESS":
        obs_2 = res_2.observation_record
        print(f"Track Type: {obs_2['normalized_data'].get('transcript_type')}")
        print(f"Language: {obs_2['normalized_data'].get('language')}")
        print(f"Segment Count: {obs_2['normalized_data'].get('segment_count')}")
        if obs_2['normalized_data'].get('segments'):
            print(f"Sample Segment: {obs_2['normalized_data']['segments'][0]}")
        (out_dir / "youtube_transcript_manual_001.json").write_text(json.dumps(obs_2, indent=2), encoding="utf-8")

    # Target 3: Public Video with Automatic Captions (PSY - Gangnam Style)
    url_3 = "https://www.youtube.com/watch?v=9bZkp7q19f0"
    print(f"\n[Test 3] read_transcript() (Automatic Captions) on: {url_3}")
    res_3 = router.read_transcript(
        url=url_3,
        product_id="PROD_TEST_YT_01",
        brand_id="BRAND_TEST",
        preferred_languages=["ko", "en"],
    )
    print(f"Status: {res_3.status}, Latency: {res_3.latency_ms:.2f}ms")
    if res_3.status == "SUCCESS":
        obs_3 = res_3.observation_record
        print(f"Track Type: {obs_3['normalized_data'].get('transcript_type')}")
        print(f"Language: {obs_3['normalized_data'].get('language')}")
        print(f"Segment Count: {obs_3['normalized_data'].get('segment_count')}")
        if obs_3['normalized_data'].get('segments'):
            print(f"Sample Segment: {obs_3['normalized_data']['segments'][0]}")
        (out_dir / "youtube_transcript_auto_001.json").write_text(json.dumps(obs_3, indent=2), encoding="utf-8")

    print("\n==================================================")
    print("LIVE YOUTUBE OBSERVATION RUN COMPLETE")
    print(f"Artifacts saved to: {out_dir}")
    print("==================================================")


if __name__ == "__main__":
    run_live_youtube_observation()
