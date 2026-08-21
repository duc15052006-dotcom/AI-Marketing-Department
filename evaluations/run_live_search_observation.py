"""Live Web Search Observation & Search-to-Read-Page Pipeline Runner (Non-LLM).

Executes real search discovery requests using ObservationRouter and SearchManager.
Validates search discovery and end-to-end search-to-read_page pipeline on public sources.
Writes sanitized evaluation artifacts to evaluations/live/observation/search/.
"""

import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.observation.router import ObservationRouter


def run_live_search_observation():
    print("==================================================")
    print("PHASE 3C.3: LIVE SEARCH OBSERVATION VALIDATION (NON-LLM)")
    print("==================================================")

    out_dir = Path(__file__).resolve().parent / "live" / "observation" / "search"
    out_dir.mkdir(parents=True, exist_ok=True)

    router = ObservationRouter()

    # Query 1: Wikipedia OpenSearch discovery
    query_1 = "Marketing strategy"
    print(f"\n[Test 1] search_web() on Wikipedia OpenSearch: '{query_1}'")
    res_1 = router.search_web(
        query=query_1,
        product_id="PROD_TEST_SEARCH_01",
        brand_id="BRAND_TEST",
        preferred_backend="wikipedia",
        max_results=5,
    )
    print(f"Status: {res_1.status}, Latency: {res_1.latency_ms:.2f}ms")
    first_url = None
    if res_1.status == "SUCCESS":
        obs_1 = res_1.observation_record
        search_res = obs_1["normalized_data"]["search_results"]
        print(f"Backend: {search_res.get('backend')} ({search_res.get('backend_provenance')})")
        print(f"Results Count: {search_res.get('result_count')}")
        if search_res.get("results"):
            top = search_res["results"][0]
            print(f"Top Hit: {top.get('title')} -> {top.get('url')}")
            first_url = top.get("url")
        (out_dir / "search_discovery_001.json").write_text(json.dumps(obs_1, indent=2), encoding="utf-8")

    # Query 2: General Discovery query
    query_2 = "Python packaging guide"
    print(f"\n[Test 2] search_web() on general web: '{query_2}'")
    res_2 = router.search_web(
        query=query_2,
        product_id="PROD_TEST_SEARCH_01",
        brand_id="BRAND_TEST",
        max_results=5,
    )
    print(f"Status: {res_2.status}, Latency: {res_2.latency_ms:.2f}ms")
    if res_2.status == "SUCCESS":
        obs_2 = res_2.observation_record
        search_res_2 = obs_2["normalized_data"]["search_results"]
        print(f"Backend: {search_res_2.get('backend')} ({search_res_2.get('backend_provenance')})")
        print(f"Results Count: {search_res_2.get('result_count')}")
        (out_dir / "search_discovery_002.json").write_text(json.dumps(obs_2, indent=2), encoding="utf-8")

    # Test 3: End-to-End Pipeline (search discovery -> read_page)
    if first_url:
        print(f"\n[Test 3] End-to-End Pipeline: read_page() on discovered URL: {first_url}")
        res_page = router.read_page(
            url=first_url,
            product_id="PROD_TEST_SEARCH_01",
            brand_id="BRAND_TEST",
        )
        print(f"Status: {res_page.status}, Latency: {res_page.latency_ms:.2f}ms")
        if res_page.status == "SUCCESS":
            page_obs = res_page.observation_record
            norm_page = page_obs["normalized_data"]
            print(f"Extracted Page Title: {norm_page.get('title')}")
            print(f"Main Text Length: {len(norm_page.get('main_text') or '')} chars")
            print(f"Headings Count: {len(norm_page.get('headings') or [])}")
            (out_dir / "search_to_read_page_001.json").write_text(json.dumps(page_obs, indent=2), encoding="utf-8")

    print("\n==================================================")
    print("LIVE SEARCH OBSERVATION RUN COMPLETE")
    print(f"Artifacts saved to: {out_dir}")
    print("==================================================")


if __name__ == "__main__":
    run_live_search_observation()
