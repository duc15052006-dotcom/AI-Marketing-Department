"""HTTP Static Web Observation Backend.

Implements deterministic HTTP web retrieval, safe streaming size checks,
content-type filtering, redirect loop prevention, and structured HTML parsing.
Preserves separated semantic confidence and strict epistemic boundaries.
"""

from __future__ import annotations

import json
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Set
import bs4
import httpx
import trafilatura
from tools.gateway.contracts import CostClass, ToolError
from tools.gateway.http_transport import PinnedDNSHTTPTransport
from tools.gateway.security import SecurityValidator, SecurityValidationError
from tools.observation.models import (
    ContentTrustLevel,
    ContentTruthStatus,
    EpistemicType,
    ExtractionConfidence,
    ExtractionQualityMetrics,
    ObservationRecord,
    SourceCredibility,
)


class HttpStaticBackend:
    """Deterministic HTTP GET and static HTML extraction engine."""

    BACKEND_ID = "http_static"
    COST_CLASS = CostClass.COST_0_LIGHT

    ALLOWED_CONTENT_TYPES = {
        "text/html",
        "application/xhtml+xml",
    }

    DISALLOWED_CONTENT_TYPES = {
        "application/pdf",
        "application/zip",
        "application/octet-stream",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "video/mp4",
        "video/webm",
        "audio/mpeg",
    }

    def __init__(
        self,
        default_timeout: float = 15.0,
        max_redirects: int = 5,
        max_wire_bytes: int = SecurityValidator.MAX_WIRE_BYTES,
        max_decoded_bytes: int = SecurityValidator.MAX_DECODED_BYTES,
    ) -> None:
        self.default_timeout = default_timeout
        self.max_redirects = max_redirects
        self.max_wire_bytes = max_wire_bytes
        self.max_decoded_bytes = max_decoded_bytes

    def read_page(
        self,
        url: str,
        product_id: str,
        brand_id: str,
        timeout: Optional[float] = None,
        allowed_domains: Optional[List[str]] = None,
    ) -> tuple[Optional[ObservationRecord], Optional[ToolError]]:
        """Fetch URL via HTTP and extract main readable text and structural headings."""
        return self._fetch_and_extract(
            url=url,
            capability="read_page",
            product_id=product_id,
            brand_id=brand_id,
            timeout=timeout,
            allowed_domains=allowed_domains,
            extract_full_text=True,
        )

    def analyze_url(
        self,
        url: str,
        product_id: str,
        brand_id: str,
        timeout: Optional[float] = None,
        allowed_domains: Optional[List[str]] = None,
    ) -> tuple[Optional[ObservationRecord], Optional[ToolError]]:
        """Fetch URL and extract OpenGraph tags, JSON-LD schemas, meta tags, and page metadata."""
        return self._fetch_and_extract(
            url=url,
            capability="analyze_url",
            product_id=product_id,
            brand_id=brand_id,
            timeout=timeout,
            allowed_domains=allowed_domains,
            extract_full_text=False,
        )

    def _fetch_and_extract(
        self,
        url: str,
        capability: str,
        product_id: str,
        brand_id: str,
        timeout: Optional[float] = None,
        allowed_domains: Optional[List[str]] = None,
        extract_full_text: bool = True,
    ) -> tuple[Optional[ObservationRecord], Optional[ToolError]]:
        t0 = time.perf_counter()
        req_timeout = timeout or self.default_timeout

        # 1. SSRF and Target Validation
        try:
            current_url = SecurityValidator.validate_url(url, allowed_domains)
        except SecurityValidationError as e:
            return None, ToolError(
                error_code=e.code,
                message=e.message,
                backend_used=self.BACKEND_ID,
                retryable=False,
            )
        except Exception as e:
            return None, ToolError(
                error_code="VALIDATION_ERROR",
                message=str(e),
                backend_used=self.BACKEND_ID,
                retryable=False,
            )

        t_val = time.perf_counter()
        validation_latency_ms = (t_val - t0) * 1000.0

        # 2. Execute HTTP GET with Safe Redirect Following & Loop Detection
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 AntigravityMarketingBot/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        visited_urls: Set[str] = {current_url}
        redirect_count = 0
        response = None
        html_text = ""
        raw_wire_bytes = 0

        t_net_start = time.perf_counter()

        try:
            with httpx.Client(
                timeout=req_timeout,
                follow_redirects=False,
                headers=headers,
                transport=PinnedDNSHTTPTransport(),
                trust_env=False,
            ) as client:
                while redirect_count <= self.max_redirects:
                    response = client.get(current_url)

                    # Handle Redirects safely
                    if response.is_redirect:
                        redirect_count += 1
                        if redirect_count > self.max_redirects:
                            return None, ToolError(
                                error_code="TOO_MANY_REDIRECTS",
                                message=f"Exceeded maximum redirect limit ({self.max_redirects}).",
                                backend_used=self.BACKEND_ID,
                                retryable=False,
                            )

                        raw_location = response.headers.get("Location")
                        if not raw_location:
                            return None, ToolError(
                                error_code="INVALID_REDIRECT",
                                message="Received redirect response with missing Location header.",
                                backend_used=self.BACKEND_ID,
                                retryable=False,
                            )

                        # Resolve relative redirect URL against current URL
                        resolved_target = urllib.parse.urljoin(current_url, raw_location)

                        # Redirect loop detection
                        if resolved_target in visited_urls:
                            return None, ToolError(
                                error_code="REDIRECT_LOOP_DETECTED",
                                message=f"Redirect loop detected: '{resolved_target}' was already visited.",
                                backend_used=self.BACKEND_ID,
                                retryable=False,
                            )
                        visited_urls.add(resolved_target)

                        # Re-validate redirect target URL for SSRF & credentials safety!
                        try:
                            current_url = SecurityValidator.validate_url(resolved_target, allowed_domains)
                        except SecurityValidationError as e:
                            return None, ToolError(
                                error_code=f"SSRF_REDIRECT_{e.code}",
                                message=f"Redirect to unsafe destination blocked: {e.message}",
                                backend_used=self.BACKEND_ID,
                                retryable=False,
                            )
                        continue
                    else:
                        break

                if response is None:
                    return None, ToolError(
                        error_code="NO_RESPONSE",
                        message="No response received from target server.",
                        backend_used=self.BACKEND_ID,
                        retryable=True,
                    )

                # Content-Type Validation
                content_type_header = response.headers.get("content-type", "").lower()
                mime_type = content_type_header.split(";")[0].strip()

                if mime_type in self.DISALLOWED_CONTENT_TYPES or (
                    mime_type and not any(mime_type.startswith(allowed) for allowed in self.ALLOWED_CONTENT_TYPES)
                ):
                    return None, ToolError(
                        error_code="UNSUPPORTED_CONTENT_TYPE",
                        message=f"Content-type '{mime_type}' is not supported for HTML observation.",
                        backend_used=self.BACKEND_ID,
                        retryable=False,
                        details={"content_type": content_type_header},
                    )

                if response.status_code >= 400:
                    return None, ToolError(
                        error_code=f"HTTP_{response.status_code}",
                        message=f"Target returned HTTP {response.status_code}: {response.reason_phrase}",
                        backend_used=self.BACKEND_ID,
                        retryable=(response.status_code in {408, 429, 500, 502, 503, 504}),
                        details={"status_code": response.status_code, "final_url": current_url},
                    )

                # Enforce Wire Size Limit
                content_bytes = response.content
                raw_wire_bytes = len(content_bytes)
                if raw_wire_bytes > self.max_wire_bytes:
                    return None, ToolError(
                        error_code="RESPONSE_TOO_LARGE",
                        message=f"Response wire size ({raw_wire_bytes} bytes) exceeds limit ({self.max_wire_bytes} bytes).",
                        backend_used=self.BACKEND_ID,
                        retryable=False,
                    )

                # Decode & Enforce Decoded Size Limit
                html_text = response.text
                if len(html_text.encode("utf-8")) > self.max_decoded_bytes:
                    return None, ToolError(
                        error_code="RESPONSE_TOO_LARGE",
                        message=f"Decoded response size ({len(html_text)} chars) exceeds limit ({self.max_decoded_bytes} bytes).",
                        backend_used=self.BACKEND_ID,
                        retryable=False,
                    )

        except SecurityValidationError as e:
            # The DNS-pinned transport re-validates at the actual connection
            # boundary, so rebinding from public to private remains a security
            # rejection rather than being mislabeled as a generic network error.
            return None, ToolError(
                error_code=e.code,
                message=e.message,
                backend_used=self.BACKEND_ID,
                retryable=False,
            )
        except httpx.TimeoutException:
            return None, ToolError(
                error_code="TIMEOUT",
                message=f"Request to '{url}' timed out after {req_timeout}s.",
                backend_used=self.BACKEND_ID,
                retryable=True,
            )
        except httpx.RequestError as e:
            return None, ToolError(
                error_code="CONNECTION_ERROR",
                message=f"HTTP connection failed: {type(e).__name__}: {str(e)}",
                backend_used=self.BACKEND_ID,
                retryable=True,
            )
        except Exception as e:
            return None, ToolError(
                error_code="HTTP_CLIENT_ERROR",
                message=f"Unexpected client failure: {type(e).__name__}: {str(e)}",
                backend_used=self.BACKEND_ID,
                retryable=False,
            )

        t_net_end = time.perf_counter()
        network_latency_ms = (t_net_end - t_net_start) * 1000.0

        # 3. Parse Metadata and OpenGraph with BeautifulSoup
        t_parse_start = time.perf_counter()
        metadata = self._extract_metadata(html_text, current_url)

        # 4. Extract Main Article/Text Content with Trafilatura
        main_text = ""
        if extract_full_text:
            extracted = trafilatura.extract(
                html_text,
                include_comments=False,
                include_tables=True,
                no_fallback=False,
                favor_recall=True,
            )
            main_text = extracted or ""

        t_parse_end = time.perf_counter()
        parse_latency_ms = (t_parse_end - t_parse_start) * 1000.0
        total_latency_ms = (t_parse_end - t0) * 1000.0

        # 5. Extraction Quality Metrics & Confidence Calculation
        quality_metrics = ExtractionQualityMetrics(
            text_length=len(main_text) if extract_full_text else len(metadata.get("description", "")),
            title_present=bool(metadata.get("title")),
            main_text_present=bool(main_text.strip()) if extract_full_text else True,
            metadata_present=bool(metadata.get("opengraph") or metadata.get("description")),
            canonical_present=bool(metadata.get("canonical_url")),
        )

        if quality_metrics.title_present and quality_metrics.main_text_present:
            ext_conf = ExtractionConfidence.HIGH
        elif quality_metrics.title_present or quality_metrics.main_text_present:
            ext_conf = ExtractionConfidence.MEDIUM
        else:
            ext_conf = ExtractionConfidence.LOW

        normalized_data = {
            "url": current_url,
            "title": metadata.get("title", ""),
            "canonical_url": metadata.get("canonical_url"),
            "meta_description": metadata.get("description", ""),
            "opengraph": metadata.get("opengraph", {}),
            "twitter_card": metadata.get("twitter_card", {}),
            "json_ld": metadata.get("json_ld", []),
            "headings": metadata.get("headings", []),
            "main_text": main_text if extract_full_text else "",
            "text_length_chars": len(main_text) if extract_full_text else 0,
            "raw_byte_count": raw_wire_bytes,
            "http_status": response.status_code,
            "extraction_quality": quality_metrics.model_dump(),
            "telemetry": {
                "validation_latency_ms": round(validation_latency_ms, 2),
                "network_latency_ms": round(network_latency_ms, 2),
                "parse_latency_ms": round(parse_latency_ms, 2),
                "total_latency_ms": round(total_latency_ms, 2),
            },
        }

        # 6. Build Normalized ObservationRecord with Strict Epistemic Separation
        obs = ObservationRecord(
            capability=capability,
            source_platform="web",
            source_type="article" if extract_full_text else "landing_page_metadata",
            source_url_or_id=current_url,
            backend_used=self.BACKEND_ID,
            collection_method="DIRECT_HTTP",
            normalized_data=normalized_data,
            evidence_class=EpistemicType.OBSERVATION,
            extraction_confidence=ext_conf,
            source_credibility=SourceCredibility.UNKNOWN,
            content_truth_status=ContentTruthStatus.UNVERIFIED,
            limitations=[
                "Static HTML observation; client-side JavaScript execution not evaluated",
                "Source credibility is UNKNOWN; external text asserts claims that remain UNVERIFIED",
            ],
            product_id=product_id,
            brand_id=brand_id,
            content_trust=ContentTrustLevel.UNTRUSTED_EXTERNAL,
        )

        return obs, None

    def _extract_metadata(self, html_text: str, current_url: str) -> Dict[str, Any]:
        """Extract metadata tags, OpenGraph, Twitter cards, and JSON-LD schemas."""
        try:
            soup = bs4.BeautifulSoup(html_text, "html.parser")
        except Exception:
            return {}

        result: Dict[str, Any] = {
            "title": "",
            "canonical_url": None,
            "description": "",
            "opengraph": {},
            "twitter_card": {},
            "json_ld": [],
            "headings": [],
        }

        # Title
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            result["title"] = title_tag.string.strip()

        # Canonical URL
        canonical_tag = soup.find("link", rel=lambda val: val and "canonical" in val.lower())
        if canonical_tag and canonical_tag.get("href"):
            result["canonical_url"] = urllib.parse.urljoin(current_url, canonical_tag["href"].strip())

        # Meta tags
        for meta in soup.find_all("meta"):
            name = meta.get("name", "").lower()
            prop = meta.get("property", "").lower()
            content = meta.get("content", "").strip()

            if not content:
                continue

            if name == "description":
                result["description"] = content
            elif prop.startswith("og:"):
                key = prop[3:]
                result["opengraph"][key] = content
            elif name.startswith("twitter:"):
                key = name[8:]
                result["twitter_card"][key] = content

        # Fallback title from og:title
        if not result["title"] and "title" in result["opengraph"]:
            result["title"] = result["opengraph"]["title"]

        # Fallback description from og:description
        if not result["description"] and "description" in result["opengraph"]:
            result["description"] = result["opengraph"]["description"]

        # Headings
        headings = []
        for tag in soup.find_all(["h1", "h2"]):
            h_text = tag.get_text().strip()
            if h_text and len(h_text) < 300:
                headings.append({"level": tag.name, "text": h_text})
        result["headings"] = headings[:20]

        # JSON-LD discovery
        json_ld_blocks = []
        for script in soup.find_all("script", type="application/ld+json"):
            if script.string:
                try:
                    parsed_json = json.loads(script.string.strip())
                    json_ld_blocks.append(parsed_json)
                except Exception:
                    continue
        result["json_ld"] = json_ld_blocks[:5]

        return result
