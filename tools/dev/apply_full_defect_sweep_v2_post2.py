"""Search truth hardening discovered during consolidated audit.

Never convert complete backend outage into a successful zero-result search.
A genuine empty response may be NO_RESULTS; mixed empty/degraded responses are
explicitly marked partial degradation.  Raw network exception text is not
reflected through ToolError messages.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "tools" / "observation" / "search_backend.py"
text = PATH.read_text(encoding="utf-8")


def replace(old: str, new: str, count: int = 1) -> None:
    global text
    actual = text.count(old)
    if actual != count:
        raise RuntimeError(f"SEARCH_SWEEP_DRIFT expected {count}, found {actual}: {old[:100]!r}")
    text = text.replace(old, new)


replace(
    '''        except Exception as e:
            return None, ToolError(
                error_code="SEARXNG_UNAVAILABLE",
                message=f"Could not connect to SearXNG at {self.base_url}: {str(e)}",
                backend_used=self.BACKEND_ID,
                retryable=True,
            )
''',
    '''        except Exception:
            return None, ToolError(
                error_code="SEARXNG_UNAVAILABLE",
                message="Could not connect to the configured SearXNG backend.",
                backend_used=self.BACKEND_ID,
                retryable=True,
            )
''',
)
replace(
    '''        headers = {"User-Agent": "AntigravityMarketingObservationBot/1.0"}
''',
    '''        headers = {"User-Agent": "AIMarketingDepartmentObservationBot/1.0"}
''',
)
replace(
    '''        except Exception as e:
            return None, ToolError(
                error_code="NETWORK_ERROR",
                message=f"Failed to query Wikipedia OpenSearch API: {str(e)}",
                backend_used=self.BACKEND_ID,
                retryable=True,
            )
''',
    '''        except Exception:
            return None, ToolError(
                error_code="NETWORK_ERROR",
                message="Failed to reach Wikipedia OpenSearch API.",
                backend_used=self.BACKEND_ID,
                retryable=True,
            )
''',
)
replace(
    '''        except Exception as e:
            return None, ToolError(
                error_code="NETWORK_ERROR",
                message=f"Failed to fetch DuckDuckGo search: {str(e)}",
                backend_used=self.BACKEND_ID,
                retryable=True,
            )
''',
    '''        except Exception:
            return None, ToolError(
                error_code="NETWORK_ERROR",
                message="Failed to reach DuckDuckGo search backend.",
                backend_used=self.BACKEND_ID,
                retryable=True,
            )
''',
)

replace(
    '''        last_error: Optional[ToolError] = None
        result_set: Optional[SearchResultSet] = None
        used_backend_name: str = "none"

        for b_name, backend, effective_scope in backends:
''',
    '''        last_error: Optional[ToolError] = None
        result_set: Optional[SearchResultSet] = None
        used_backend_name: str = "none"
        successful_empty_backends: List[str] = []
        backend_errors: List[Dict[str, Any]] = []

        for b_name, backend, effective_scope in backends:
''',
)
replace(
    '''            if res_set and not err and res_set.result_count > 0:
                result_set = res_set
                used_backend_name = b_name
                break
            if err:
                last_error = err

        if not result_set:
            if last_error and not last_error.retryable:
                return None, last_error
            result_set = SearchResultSet(
                query=cleaned_query,
                executed_query=cleaned_query,
                backend="none",
                backend_provenance="NO_RESULTS",
                search_scope=search_scope,
                result_count=0,
                results=[],
                collection_limit=bounded_max_results,
            )
''',
    '''            if res_set and not err and res_set.result_count > 0:
                result_set = res_set
                used_backend_name = b_name
                break
            if res_set is not None and not err:
                successful_empty_backends.append(b_name)
            if err:
                last_error = err
                backend_errors.append({
                    "backend": b_name,
                    "error_code": err.error_code,
                    "retryable": bool(err.retryable),
                })

        if not result_set:
            # Complete outage/degradation is an error, not a successful
            # zero-result observation. This preserves the user's ability to
            # distinguish "nothing found" from "search unavailable".
            if not successful_empty_backends and last_error is not None:
                return None, last_error
            provenance = "NO_RESULTS_PARTIAL_DEGRADATION" if backend_errors else "NO_RESULTS"
            result_set = SearchResultSet(
                query=cleaned_query,
                executed_query=cleaned_query,
                backend="none",
                backend_provenance=provenance,
                search_scope=search_scope,
                result_count=0,
                results=[],
                collection_limit=bounded_max_results,
            )
''',
)
replace(
    '''                "backend_provenance": result_set.backend_provenance,
                "allowed_domains": allowed_domains or [],
''',
    '''                "backend_provenance": result_set.backend_provenance,
                "successful_empty_backends": successful_empty_backends,
                "backend_errors": backend_errors,
                "allowed_domains": allowed_domains or [],
''',
)

PATH.write_text(text, encoding="utf-8")
print("FULL_DEFECT_SWEEP_V2_SEARCH_TRUTH_APPLIED")
