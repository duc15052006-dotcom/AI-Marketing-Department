"""Public Discussion Observation Backend (Reddit + Generic Forum & Hacker News).

Provides read-only observation capabilities for public discussion threads, comments,
and community search results. Enforces privacy minimization, sampling metadata,
rate-limit control, bounded pagination, and untrusted data boundaries.
"""

from __future__ import annotations

import os
import re
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import bs4
import httpx
from tools.gateway.contracts import CostClass, ToolError
from tools.gateway.security import SecurityValidator, SecurityValidationError
from tools.observation.http_backend import HttpStaticBackend
from tools.observation.models import (
    ContentTrustLevel,
    ContentTruthStatus,
    ContentVariant,
    DiscussionComment,
    DiscussionSearchSummary,
    DiscussionThread,
    EpistemicType,
    ExtractionConfidence,
    IdentityType,
    ObservationRecord,
    RedditAuthState,
    RedditCapabilityState,
    RedditPolicyState,
    SourceCredibility,
)


class PublicDiscussionBackend:
    """Dedicated read-only public discussion and forum observation backend."""

    BACKEND_ID = "discussion_public"
    COST_CLASS = CostClass.COST_0_LIGHT

    # Bounded limits
    MAX_THREADS_PER_REQUEST = 50
    MAX_COMMENTS_PER_THREAD = 100
    MAX_PAGES_PER_CALL = 3
    DEFAULT_TIMEOUT = 15.0

    # User Agent
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AntigravityMarketingObservationBot/1.0"

    def __init__(
        self,
        http_static_backend: Optional[HttpStaticBackend] = None,
        default_timeout: float = 15.0,
    ) -> None:
        self.http_static = http_static_backend or HttpStaticBackend()
        self.default_timeout = default_timeout
        self.last_request_time: float = 0.0
        self.min_request_interval_sec: float = 0.5  # Polite rate limiting

    def get_reddit_policy_status(self) -> Dict[str, Any]:
        """Check Reddit auth and policy status without assuming credentials alone permit commercial use."""
        has_client_id = bool(os.environ.get("REDDIT_CLIENT_ID"))
        has_secret = bool(os.environ.get("REDDIT_CLIENT_SECRET"))
        auth_state = RedditAuthState.CONFIGURED if (has_client_id and has_secret) else RedditAuthState.NOT_CONFIGURED

        # Policy state: Reddit terms require explicit review/agreement for commercial/automated usage
        policy_state = RedditPolicyState.COMMERCIAL_APPROVAL_REQUIRED if auth_state == RedditAuthState.CONFIGURED else RedditPolicyState.UNVERIFIED
        capability_state = (
            RedditCapabilityState.READY
            if (auth_state == RedditAuthState.CONFIGURED and policy_state == RedditPolicyState.APPROVED)
            else (RedditCapabilityState.BLOCKED_POLICY if auth_state == RedditAuthState.CONFIGURED else RedditCapabilityState.BLOCKED_AUTH)
        )

        return {
            "auth_state": auth_state.value,
            "policy_state": policy_state.value,
            "capability_state": capability_state.value,
        }

    def _rate_limit_pause(self) -> None:
        """Enforce polite inter-request delay."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_request_interval_sec:
            time.sleep(self.min_request_interval_sec - elapsed)
        self.last_request_time = time.time()

    def identify_platform(self, url: str) -> str:
        """Classify discussion platform by URL structure."""
        url_lower = url.lower()
        if "reddit.com" in url_lower or "redd.it" in url_lower:
            return "reddit"
        elif "news.ycombinator.com" in url_lower or "hn.algolia.com" in url_lower:
            return "hacker_news"
        elif "/t/" in url_lower or "discourse" in url_lower:
            return "discourse"
        return "web_forum"

    def read_forum_thread(
        self,
        url: str,
        product_id: str,
        brand_id: str,
        max_comments: int = 50,
        timeout: Optional[float] = None,
    ) -> Tuple[Optional[ObservationRecord], Optional[ToolError]]:
        """Fetch a public forum or discussion thread and extract structured header and comments."""
        t0 = time.perf_counter()
        req_timeout = timeout or self.default_timeout
        bounded_max_comments = min(max(1, max_comments), self.MAX_COMMENTS_PER_THREAD)

        # 1. SSRF & Scheme Validation
        try:
            validated_url = SecurityValidator.validate_url(url)
        except SecurityValidationError as e:
            return None, ToolError(
                error_code=e.code,
                message=e.message,
                backend_used=self.BACKEND_ID,
                retryable=False,
            )

        platform = self.identify_platform(validated_url)

        # 2. Dispatch to Platform Handler
        if platform == "hacker_news":
            thread, err = self._fetch_hacker_news_thread(validated_url, bounded_max_comments, req_timeout)
        elif platform == "reddit":
            thread, err = self._fetch_reddit_thread(validated_url, bounded_max_comments, req_timeout)
        else:
            thread, err = self._fetch_generic_web_forum_thread(validated_url, bounded_max_comments, req_timeout)

        if err:
            return None, err

        if not thread:
            return None, ToolError(
                error_code="THREAD_NOT_FOUND",
                message=f"Discussion thread at '{url}' could not be parsed.",
                backend_used=self.BACKEND_ID,
            )

        t_end = time.perf_counter()
        total_latency_ms = (t_end - t0) * 1000.0

        # 3. Calculate Extraction Confidence (Mechanical completeness)
        has_title = bool(thread.title)
        has_body = bool(thread.body or thread.comments)
        if has_title and has_body:
            ext_conf = ExtractionConfidence.HIGH
        elif has_title:
            ext_conf = ExtractionConfidence.MEDIUM
        else:
            ext_conf = ExtractionConfidence.LOW

        normalized_payload = {
            "thread": thread.model_dump(),
            "sampling_context": {
                "platform": platform,
                "upstream_provenance": thread.upstream_provenance,
                "thread_url": validated_url,
                "requested_max_comments": bounded_max_comments,
                "comments_collected": len(thread.comments),
                "collected_at": datetime.now(timezone.utc).isoformat(),
            },
            "telemetry": {
                "total_latency_ms": round(total_latency_ms, 2),
            },
        }

        obs = ObservationRecord(
            capability="read_forum_thread",
            source_platform=platform,
            source_type="discussion_thread",
            source_url_or_id=validated_url,
            backend_used=self.BACKEND_ID,
            collection_method="PUBLIC_JSON_API" if platform in ("hacker_news", "reddit") else "FORUM_DOM_PARSE",
            normalized_data=normalized_payload,
            evidence_class=EpistemicType.OBSERVATION,
            extraction_confidence=ext_conf,
            source_credibility=SourceCredibility.UNKNOWN,
            content_truth_status=ContentTruthStatus.UNVERIFIED,
            limitations=[
                f"Public discussion observation from {platform} (Provenance: {thread.upstream_provenance})",
                f"Sample contains {len(thread.comments)} collected comments out of reported total ({thread.reported_comment_count or 'unknown'})",
                "Community statements are pseudonymous public opinions/observations, not verified factual claims",
            ],
            product_id=product_id,
            brand_id=brand_id,
            content_trust=ContentTrustLevel.UNTRUSTED_EXTERNAL,
        )

        return obs, None

    def search_public_discussions(
        self,
        query: str,
        product_id: str,
        brand_id: str,
        platform: Optional[str] = "hacker_news",
        community: Optional[str] = None,
        sort: str = "relevance",
        time_range: Optional[str] = None,
        max_results: int = 20,
        timeout: Optional[float] = None,
    ) -> Tuple[Optional[ObservationRecord], Optional[ToolError]]:
        """Search public discussions across supported platforms with explicit sampling metadata."""
        t0 = time.perf_counter()
        req_timeout = timeout or self.default_timeout
        bounded_max_results = min(max(1, max_results), self.MAX_THREADS_PER_REQUEST)
        target_platform = (platform or "hacker_news").lower()

        if not query or not query.strip():
            return None, ToolError(
                error_code="EMPTY_QUERY",
                message="Search query must be a non-empty string.",
                backend_used=self.BACKEND_ID,
            )

        if target_platform == "hacker_news":
            summary, err = self._search_hacker_news(
                query=query.strip(),
                sort=sort,
                max_results=bounded_max_results,
                timeout=req_timeout,
            )
        elif target_platform == "reddit":
            summary, err = self._search_reddit(
                query=query.strip(),
                community=community,
                sort=sort,
                max_results=bounded_max_results,
                timeout=req_timeout,
            )
        else:
            return None, ToolError(
                error_code="UNSUPPORTED_PLATFORM",
                message=f"Platform '{platform}' is not supported for public discussion search in Phase 3C.2.",
                backend_used=self.BACKEND_ID,
                retryable=False,
            )

        if err:
            return None, err

        t_end = time.perf_counter()
        total_latency_ms = (t_end - t0) * 1000.0

        ext_conf = ExtractionConfidence.HIGH if summary.result_count > 0 else ExtractionConfidence.MEDIUM

        normalized_payload = {
            "search_summary": summary.model_dump(),
            "sampling_context": {
                "query": query.strip(),
                "platform": target_platform,
                "upstream_provenance": summary.upstream_provenance,
                "community_scope": community,
                "sort_method": sort,
                "time_window": time_range,
                "result_count": summary.result_count,
                "collection_limit": bounded_max_results,
                "has_more": summary.has_more,
                "collected_at": datetime.now(timezone.utc).isoformat(),
            },
            "telemetry": {
                "total_latency_ms": round(total_latency_ms, 2),
            },
        }

        obs = ObservationRecord(
            capability="search_public_discussions",
            source_platform=target_platform,
            source_type="discussion_search_result",
            source_url_or_id=f"{target_platform}://search?q={urllib.parse.quote(query.strip())}",
            backend_used=self.BACKEND_ID,
            collection_method="PUBLIC_JSON_API",
            normalized_data=normalized_payload,
            evidence_class=EpistemicType.OBSERVATION,
            extraction_confidence=ext_conf,
            source_credibility=SourceCredibility.UNKNOWN,
            content_truth_status=ContentTruthStatus.UNVERIFIED,
            limitations=[
                f"Public search query on {target_platform} via {summary.upstream_provenance} within bounded limit ({bounded_max_results})",
                "Results reflect user discussion titles and snippets, not verified market statistics",
            ],
            product_id=product_id,
            brand_id=brand_id,
            content_trust=ContentTrustLevel.UNTRUSTED_EXTERNAL,
        )

        return obs, None

    # -------------------------------------------------------------
    # Platform Specific Adapters (Hacker News Algolia API)
    # -------------------------------------------------------------
    def _fetch_hacker_news_thread(
        self, url: str, max_comments: int, timeout: float
    ) -> Tuple[Optional[DiscussionThread], Optional[ToolError]]:
        """Fetch Hacker News discussion thread via official Algolia item endpoint."""
        item_id = self._extract_hn_item_id(url)
        if not item_id:
            return None, ToolError(
                error_code="INVALID_THREAD_ID",
                message=f"Could not extract Hacker News item ID from URL '{url}'.",
                backend_used=self.BACKEND_ID,
            )

        api_url = f"https://hn.algolia.com/api/v1/items/{item_id}"
        self._rate_limit_pause()

        try:
            with httpx.Client(timeout=timeout, headers={"User-Agent": self.USER_AGENT}) as client:
                resp = client.get(api_url)
                if resp.status_code == 404:
                    return None, ToolError(
                        error_code="THREAD_NOT_FOUND",
                        message=f"Hacker News thread {item_id} not found.",
                        backend_used=self.BACKEND_ID,
                    )
                if resp.status_code == 429:
                    return None, ToolError(
                        error_code="RATE_LIMITED",
                        message="Hacker News API rate limit reached.",
                        backend_used=self.BACKEND_ID,
                        retryable=True,
                    )
                if resp.status_code != 200:
                    return None, ToolError(
                        error_code=f"HTTP_{resp.status_code}",
                        message=f"Hacker News API returned HTTP {resp.status_code}",
                        backend_used=self.BACKEND_ID,
                    )

                data = resp.json()
        except Exception as e:
            return None, ToolError(
                error_code="NETWORK_ERROR",
                message=f"Failed to fetch Hacker News thread: {str(e)}",
                backend_used=self.BACKEND_ID,
                retryable=True,
            )

        # Parse Tree Comments recursively with bounded count
        comments: List[DiscussionComment] = []
        self._flatten_hn_comments(
            data.get("children", []),
            thread_id=str(item_id),
            parent_id=None,
            depth=0,
            accum=comments,
            limit=max_comments,
        )

        thread = DiscussionThread(
            thread_id=str(data.get("id") or item_id),
            platform="hacker_news",
            upstream_provenance="FIRST_PARTY_OFFICIAL_API",
            thread_url=f"https://news.ycombinator.com/item?id={item_id}",
            title=data.get("title") or "Untitled Discussion",
            author_display_name=data.get("author"),
            author_platform_identifier=data.get("author"),
            identity_type=IdentityType.PSEUDONYMOUS_PLATFORM_IDENTIFIER,
            created_at=self._parse_iso_date(data.get("created_at")),
            body=data.get("text"),
            community="Hacker News",
            reported_score=data.get("points"),
            reported_comment_count=len(comments),
            outbound_links=[data["url"]] if data.get("url") else [],
            comments=comments,
        )

        return thread, None

    def _search_hacker_news(
        self, query: str, sort: str, max_results: int, timeout: float
    ) -> Tuple[Optional[DiscussionSearchSummary], Optional[ToolError]]:
        """Search Hacker News via Algolia search API."""
        endpoint = "search_by_date" if sort == "new" else "search"
        api_url = f"https://hn.algolia.com/api/v1/{endpoint}"
        params = {
            "query": query,
            "tags": "story",
            "hitsPerPage": max_results,
        }
        self._rate_limit_pause()

        try:
            with httpx.Client(timeout=timeout, headers={"User-Agent": self.USER_AGENT}) as client:
                resp = client.get(api_url, params=params)
                if resp.status_code == 429:
                    return None, ToolError(
                        error_code="RATE_LIMITED",
                        message="Hacker News search rate limited.",
                        backend_used=self.BACKEND_ID,
                        retryable=True,
                    )
                if resp.status_code != 200:
                    return None, ToolError(
                        error_code=f"HTTP_{resp.status_code}",
                        message=f"Hacker News search returned HTTP {resp.status_code}",
                        backend_used=self.BACKEND_ID,
                    )
                data = resp.json()
        except Exception as e:
            return None, ToolError(
                error_code="NETWORK_ERROR",
                message=f"Failed to execute Hacker News search: {str(e)}",
                backend_used=self.BACKEND_ID,
                retryable=True,
            )

        hits = data.get("hits", [])
        threads: List[DiscussionThread] = []

        for h in hits:
            t_id = str(h.get("objectID") or h.get("id") or "")
            if not t_id:
                continue
            thread = DiscussionThread(
                thread_id=t_id,
                platform="hacker_news",
                upstream_provenance="THIRD_PARTY_SEARCH_INDEX",
                thread_url=f"https://news.ycombinator.com/item?id={t_id}",
                title=h.get("title") or "Untitled",
                author_display_name=h.get("author"),
                author_platform_identifier=h.get("author"),
                identity_type=IdentityType.PSEUDONYMOUS_PLATFORM_IDENTIFIER,
                created_at=self._parse_iso_date(h.get("created_at")),
                body=h.get("story_text"),
                community="Hacker News",
                reported_score=h.get("points"),
                reported_comment_count=h.get("num_comments"),
                outbound_links=[h["url"]] if h.get("url") else [],
            )
            threads.append(thread)

        summary = DiscussionSearchSummary(
            query=query,
            platform="hacker_news",
            upstream_provenance="THIRD_PARTY_SEARCH_INDEX",
            sort_method=sort,
            result_count=len(threads),
            collection_limit=max_results,
            has_more=(data.get("nbPages", 0) > 1),
            threads=threads,
        )

        return summary, None

    def _flatten_hn_comments(
        self,
        children: List[Dict[str, Any]],
        thread_id: str,
        parent_id: Optional[str],
        depth: int,
        accum: List[DiscussionComment],
        limit: int,
    ) -> None:
        """Recursively flatten Algolia comment tree into bounded list."""
        for c in children:
            if len(accum) >= limit:
                return
            c_id = str(c.get("id") or "")
            if not c_id:
                continue

            body_html = c.get("text") or ""
            # Strip simple HTML markup safely for text representation
            body_text = self._strip_html(body_html) if body_html else ""
            status = "DELETED" if c.get("deleted") else ("ACTIVE" if body_text else "UNAVAILABLE")

            comment = DiscussionComment(
                comment_id=c_id,
                parent_comment_id=parent_id,
                thread_id=thread_id,
                author_display_name=c.get("author"),
                author_platform_identifier=c.get("author"),
                identity_type=IdentityType.PSEUDONYMOUS_PLATFORM_IDENTIFIER,
                created_at=self._parse_iso_date(c.get("created_at")),
                body=body_text,
                depth=depth,
                reported_score=c.get("points"),
                permalink=f"https://news.ycombinator.com/item?id={c_id}",
                status=status,
            )
            accum.append(comment)

            sub_children = c.get("children") or []
            if sub_children:
                self._flatten_hn_comments(
                    sub_children,
                    thread_id=thread_id,
                    parent_id=c_id,
                    depth=depth + 1,
                    accum=accum,
                    limit=limit,
                )

    # -------------------------------------------------------------
    # Platform Specific Adapters (Reddit Public / OAuth Layer)
    # -------------------------------------------------------------
    def _fetch_reddit_thread(
        self, url: str, max_comments: int, timeout: float
    ) -> Tuple[Optional[DiscussionThread], Optional[ToolError]]:
        """Fetch Reddit discussion thread via clean public JSON or authenticated API."""
        clean_url = url.split("?")[0].rstrip("/")
        json_url = f"{clean_url}.json" if not clean_url.endswith(".json") else clean_url

        headers = {"User-Agent": self.USER_AGENT}
        self._rate_limit_pause()

        try:
            with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
                resp = client.get(json_url)
                if resp.status_code in (401, 403):
                    return None, ToolError(
                        error_code="AUTH_REQUIRED",
                        message="Reddit API requires registered application authentication for this endpoint.",
                        backend_used=self.BACKEND_ID,
                        retryable=False,
                    )
                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After")
                    return None, ToolError(
                        error_code="RATE_LIMITED",
                        message=f"Reddit endpoint rate limited. Retry-After: {retry_after or 'unspecified'}",
                        backend_used=self.BACKEND_ID,
                        retryable=True,
                    )
                if resp.status_code != 200:
                    return None, ToolError(
                        error_code=f"HTTP_{resp.status_code}",
                        message=f"Reddit returned HTTP {resp.status_code}",
                        backend_used=self.BACKEND_ID,
                    )

                data = resp.json()
        except Exception as e:
            return None, ToolError(
                error_code="NETWORK_ERROR",
                message=f"Failed to fetch Reddit thread: {str(e)}",
                backend_used=self.BACKEND_ID,
                retryable=True,
            )

        if not isinstance(data, list) or len(data) == 0:
            return None, ToolError(
                error_code="INVALID_RESPONSE",
                message="Reddit returned unexpected non-list JSON payload.",
                backend_used=self.BACKEND_ID,
            )

        post_data = data[0].get("data", {}).get("children", [{}])[0].get("data", {})
        t_id = post_data.get("id") or "unknown"

        comments: List[DiscussionComment] = []
        raw_comments = data[1].get("data", {}).get("children", []) if len(data) > 1 else []
        self._flatten_reddit_comments(raw_comments, thread_id=t_id, parent_id=None, depth=0, accum=comments, limit=max_comments)

        thread = DiscussionThread(
            thread_id=t_id,
            platform="reddit",
            upstream_provenance="FIRST_PARTY_OFFICIAL_API",
            thread_url=f"https://www.reddit.com{post_data.get('permalink', '')}",
            title=post_data.get("title") or "Untitled",
            author_display_name=post_data.get("author"),
            author_platform_identifier=post_data.get("author"),
            identity_type=IdentityType.PSEUDONYMOUS_PLATFORM_IDENTIFIER,
            created_at=datetime.fromtimestamp(post_data.get("created_utc", 0), timezone.utc) if post_data.get("created_utc") else None,
            body=post_data.get("selftext"),
            community=f"r/{post_data.get('subreddit', '')}" if post_data.get("subreddit") else None,
            reported_score=post_data.get("score"),
            reported_comment_count=post_data.get("num_comments"),
            tags_or_flair=[post_data["link_flair_text"]] if post_data.get("link_flair_text") else [],
            outbound_links=[post_data["url"]] if post_data.get("url") and "reddit.com" not in post_data["url"] else [],
            comments=comments,
        )

        return thread, None

    def _search_reddit(
        self, query: str, community: Optional[str], sort: str, max_results: int, timeout: float
    ) -> Tuple[Optional[DiscussionSearchSummary], Optional[ToolError]]:
        """Search Reddit via public JSON endpoint or authenticated API."""
        if community:
            sub = community.replace("r/", "").strip()
            search_url = f"https://www.reddit.com/r/{sub}/search.json"
        else:
            search_url = "https://www.reddit.com/search.json"

        params = {
            "q": query,
            "sort": sort,
            "limit": max_results,
            "restrict_sr": "1" if community else "0",
        }
        headers = {"User-Agent": self.USER_AGENT}
        self._rate_limit_pause()

        try:
            with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
                resp = client.get(search_url, params=params)
                if resp.status_code in (401, 403):
                    return None, ToolError(
                        error_code="AUTH_REQUIRED",
                        message="Reddit search requires registered application credentials.",
                        backend_used=self.BACKEND_ID,
                        retryable=False,
                    )
                if resp.status_code == 429:
                    return None, ToolError(
                        error_code="RATE_LIMITED",
                        message="Reddit search is rate limited.",
                        backend_used=self.BACKEND_ID,
                        retryable=True,
                    )
                if resp.status_code != 200:
                    return None, ToolError(
                        error_code=f"HTTP_{resp.status_code}",
                        message=f"Reddit search returned HTTP {resp.status_code}",
                        backend_used=self.BACKEND_ID,
                    )
                data = resp.json()
        except Exception as e:
            return None, ToolError(
                error_code="NETWORK_ERROR",
                message=f"Failed to search Reddit: {str(e)}",
                backend_used=self.BACKEND_ID,
                retryable=True,
            )

        children = data.get("data", {}).get("children", [])
        threads: List[DiscussionThread] = []

        for item in children:
            pdata = item.get("data", {})
            t_id = pdata.get("id") or ""
            if not t_id:
                continue
            thread = DiscussionThread(
                thread_id=t_id,
                platform="reddit",
                upstream_provenance="FIRST_PARTY_OFFICIAL_API",
                thread_url=f"https://www.reddit.com{pdata.get('permalink', '')}",
                title=pdata.get("title") or "Untitled",
                author_display_name=pdata.get("author"),
                author_platform_identifier=pdata.get("author"),
                identity_type=IdentityType.PSEUDONYMOUS_PLATFORM_IDENTIFIER,
                created_at=datetime.fromtimestamp(pdata.get("created_utc", 0), timezone.utc) if pdata.get("created_utc") else None,
                body=pdata.get("selftext"),
                community=f"r/{pdata.get('subreddit', '')}" if pdata.get("subreddit") else None,
                reported_score=pdata.get("score"),
                reported_comment_count=pdata.get("num_comments"),
                tags_or_flair=[pdata["link_flair_text"]] if pdata.get("link_flair_text") else [],
            )
            threads.append(thread)

        summary = DiscussionSearchSummary(
            query=query,
            platform="reddit",
            upstream_provenance="FIRST_PARTY_OFFICIAL_API",
            community_scope=community,
            sort_method=sort,
            result_count=len(threads),
            collection_limit=max_results,
            has_more=bool(data.get("data", {}).get("after")),
            threads=threads,
        )

        return summary, None

    def _flatten_reddit_comments(
        self,
        children: List[Dict[str, Any]],
        thread_id: str,
        parent_id: Optional[str],
        depth: int,
        accum: List[DiscussionComment],
        limit: int,
    ) -> None:
        """Recursively flatten Reddit comment tree into bounded list."""
        for item in children:
            if len(accum) >= limit:
                return
            if item.get("kind") != "t1":
                continue
            cdata = item.get("data", {})
            c_id = cdata.get("id") or ""
            if not c_id:
                continue

            body = cdata.get("body") or ""
            status = "DELETED" if body == "[deleted]" else ("REMOVED" if body == "[removed]" else "ACTIVE")

            comment = DiscussionComment(
                comment_id=c_id,
                parent_comment_id=parent_id or cdata.get("parent_id"),
                thread_id=thread_id,
                author_display_name=cdata.get("author") if status == "ACTIVE" else None,
                author_platform_identifier=cdata.get("author") if status == "ACTIVE" else None,
                identity_type=IdentityType.PSEUDONYMOUS_PLATFORM_IDENTIFIER,
                created_at=datetime.fromtimestamp(cdata.get("created_utc", 0), timezone.utc) if cdata.get("created_utc") else None,
                body=body,
                depth=depth,
                reported_score=cdata.get("score"),
                permalink=f"https://www.reddit.com{cdata.get('permalink', '')}",
                status=status,
            )
            accum.append(comment)

            replies = cdata.get("replies")
            if isinstance(replies, dict):
                sub_children = replies.get("data", {}).get("children", [])
                if sub_children:
                    self._flatten_reddit_comments(
                        sub_children,
                        thread_id=thread_id,
                        parent_id=c_id,
                        depth=depth + 1,
                        accum=accum,
                        limit=limit,
                    )

    # -------------------------------------------------------------
    # Generic Web Forum HTML Adapter
    # -------------------------------------------------------------
    def _fetch_generic_web_forum_thread(
        self, url: str, max_comments: int, timeout: float
    ) -> Tuple[Optional[DiscussionThread], Optional[ToolError]]:
        """Extract generic web forum thread using safe HTML extraction."""
        obs, err = self.http_static.read_page(
            url=url,
            product_id="internal_forum_parse",
            brand_id="internal_forum_brand",
            timeout=timeout,
        )
        if err or not obs:
            return None, err or ToolError(error_code="FORUM_FETCH_FAILED", message="Failed to fetch forum page.", backend_used=self.BACKEND_ID)

        norm = obs.normalized_data
        thread = DiscussionThread(
            thread_id=re.sub(r"[^a-zA-Z0-9_-]", "_", url)[:32],
            platform="web_forum",
            upstream_provenance="DIRECT_DOM",
            thread_url=url,
            title=norm.get("title") or "Forum Discussion",
            body=norm.get("main_text"),
            outbound_links=[norm["canonical_url"]] if norm.get("canonical_url") else [],
            comments=[],
        )

        return thread, None

    # -------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------
    def _extract_hn_item_id(self, url: str) -> Optional[str]:
        """Parse item ID from Hacker News URLs."""
        match = re.search(r"[?&]id=(\d+)", url)
        if match:
            return match.group(1)
        match = re.search(r"hn\.algolia\.com/api/v1/items/(\d+)", url)
        if match:
            return match.group(1)
        return None

    def _parse_iso_date(self, val: Optional[str]) -> Optional[datetime]:
        if not val:
            return None
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except Exception:
            return None

    def _strip_html(self, html_str: str) -> str:
        try:
            soup = bs4.BeautifulSoup(html_str, "html.parser")
            return soup.get_text(separator=" ").strip()
        except Exception:
            return html_str
