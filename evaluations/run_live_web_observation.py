"""Live Web Observation Runner (Non-LLM).

Executes real public HTTP observations using ObservationRouter and HttpStaticBackend.
Tests at least 3 safe public targets and writes sanitized evaluation artifacts to evaluations/live/observation/.
"""

import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.observation.router import ObservationRouter


def run_live_web_observation():
    print("==================================================")
    print("PHASE 3C.0: LIVE WEB OBSERVATION VALIDATION (NON-LLM)")
    print("==================================================")

    out_dir = Path(__file__).resolve().parent / "live" / "observation"
    out_dir.mkdir(parents=True, exist_ok=True)

    router = ObservationRouter()

    # Target 1: Static Documentation / Article Page (Python Docs)
    url_1 = "https://docs.python.org/3/tutorial/index.html"
    print(f"\n[Test 1] read_page() on Documentation: {url_1}")
    res_1 = router.read_page(
        url=url_1,
        product_id="PROD_TEST_OBS_01",
        brand_id="BRAND_TEST",
    )
    print(f"Status: {res_1.status}, Latency: {res_1.latency_ms:.2f}ms")
    if res_1.status == "SUCCESS":
        obs_1 = res_1.observation_record
        print(f"Title: {obs_1['normalized_data'].get('title')}")
        print(f"Text Length: {obs_1['normalized_data'].get('text_length_chars')} chars")
        print(f"Headings count: {len(obs_1['normalized_data'].get('headings', []))}")
        (out_dir / "web_read_page_001.json").write_text(json.dumps(obs_1, indent=2), encoding="utf-8")

    # Target 2: Standard Semantic Web Page (Example.com)
    url_2 = "https://example.com"
    print(f"\n[Test 2] read_page() on Semantic Domain: {url_2}")
    res_2 = router.read_page(
        url=url_2,
        product_id="PROD_TEST_OBS_01",
        brand_id="BRAND_TEST",
    )
    print(f"Status: {res_2.status}, Latency: {res_2.latency_ms:.2f}ms")
    if res_2.status == "SUCCESS":
        obs_2 = res_2.observation_record
        print(f"Title: {obs_2['normalized_data'].get('title')}")
        print(f"Main Text Preview: {obs_2['normalized_data'].get('main_text')[:100]}...")
        (out_dir / "web_read_page_002.json").write_text(json.dumps(obs_2, indent=2), encoding="utf-8")

    # Target 3: Page with OpenGraph & Metadata (Wikipedia Marketing Strategy)
    url_3 = "https://en.wikipedia.org/wiki/Marketing_strategy"
    print(f"\n[Test 3] analyze_url() on Rich Metadata Target: {url_3}")
    res_3 = router.analyze_url(
        url=url_3,
        product_id="PROD_TEST_OBS_01",
        brand_id="BRAND_TEST",
    )
    print(f"Status: {res_3.status}, Latency: {res_3.latency_ms:.2f}ms")
    if res_3.status == "SUCCESS":
        obs_3 = res_3.observation_record
        print(f"Title: {obs_3['normalized_data'].get('title')}")
        print(f"Canonical URL: {obs_3['normalized_data'].get('canonical_url')}")
        print(f"OpenGraph Keys: {list(obs_3['normalized_data'].get('opengraph', {}).keys())}")
        print(f"Headings Found: {len(obs_3['normalized_data'].get('headings', []))}")
        (out_dir / "web_analyze_url_001.json").write_text(json.dumps(obs_3, indent=2), encoding="utf-8")

    print("\n==================================================")
    print("LIVE OBSERVATION RUN COMPLETE")
    print(f"Artifacts saved to: {out_dir}")
    print("==================================================")


if __name__ == "__main__":
    run_live_web_observation()
