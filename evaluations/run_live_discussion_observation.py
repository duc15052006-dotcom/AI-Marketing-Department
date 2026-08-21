"""Live Public Discussion Observation Runner (Non-LLM).

Executes real public discussion observations using ObservationRouter and PublicDiscussionBackend.
Validates public discussion thread reading and discussion search on official public APIs.
Writes sanitized evaluation artifacts to evaluations/live/observation/discussions/.
"""

import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.observation.router import ObservationRouter


def run_live_discussion_observation():
    print("==================================================")
    print("PHASE 3C.2: LIVE DISCUSSION OBSERVATION VALIDATION (NON-LLM)")
    print("==================================================")

    out_dir = Path(__file__).resolve().parent / "live" / "observation" / "discussions"
    out_dir.mkdir(parents=True, exist_ok=True)

    router = ObservationRouter()

    # Target 1: Public Discussion Thread (Hacker News Dropbox Launch)
    url_1 = "https://news.ycombinator.com/item?id=8863"
    print(f"\n[Test 1] read_forum_thread() on: {url_1}")
    res_1 = router.read_forum_thread(
        url=url_1,
        product_id="PROD_TEST_DISCUSS_01",
        brand_id="BRAND_TEST",
        max_comments=20,
    )
    print(f"Status: {res_1.status}, Latency: {res_1.latency_ms:.2f}ms")
    if res_1.status == "SUCCESS":
        obs_1 = res_1.observation_record
        thread = obs_1["normalized_data"]["thread"]
        print(f"Title: {thread.get('title')}")
        print(f"Author: {thread.get('author_display_name')}")
        print(f"Reported Score: {thread.get('reported_score')}")
        print(f"Comments Collected: {len(thread.get('comments', []))}")
        (out_dir / "discussion_thread_001.json").write_text(json.dumps(obs_1, indent=2), encoding="utf-8")

    # Target 2: Public Discussion Search (Hacker News Algolia Query)
    query_2 = "AI marketing strategy"
    print(f"\n[Test 2] search_public_discussions() for: '{query_2}'")
    res_2 = router.search_public_discussions(
        query=query_2,
        platform="hacker_news",
        sort="relevance",
        max_results=10,
        product_id="PROD_TEST_DISCUSS_01",
        brand_id="BRAND_TEST",
    )
    print(f"Status: {res_2.status}, Latency: {res_2.latency_ms:.2f}ms")
    if res_2.status == "SUCCESS":
        obs_2 = res_2.observation_record
        summary = obs_2["normalized_data"]["search_summary"]
        print(f"Results Count: {summary.get('result_count')}")
        if summary.get("threads"):
            print(f"Top Hit Title: {summary['threads'][0].get('title')}")
        (out_dir / "discussion_search_001.json").write_text(json.dumps(obs_2, indent=2), encoding="utf-8")

    print("\n==================================================")
    print("LIVE DISCUSSION OBSERVATION RUN COMPLETE")
    print(f"Artifacts saved to: {out_dir}")
    print("==================================================")


if __name__ == "__main__":
    run_live_discussion_observation()
