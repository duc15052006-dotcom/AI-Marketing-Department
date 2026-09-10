from pathlib import Path

path = Path("integrations/models/gateway.py")
text = path.read_text(encoding="utf-8")

old = '''                    except Exception as sync_e:
                        sync_err = ModelStreamError(
                            code="STREAM_INTERNAL_ERROR",
                            category="INTERNAL",
                            safe_message=f"STREAM_INTERNAL_ERROR: Internal model invocation failure on '{cand_provider}'.",
                            retryable=False,
                            http_status=None,
                        )
                        last_error = sync_err
                        last_error_provider = cand_provider
                        last_error_model = cand_model
                        if strict_model_pin or len(candidates) == 1:
                            yield normalize_public_stream_delta(
                                StreamDelta(content="", finish_reason="error", error=sync_err),
                                cand_provider,
                                cand_model,
                            )
                            return
                        continue
'''

new = '''                    except Exception as sync_e:
                        if is_timeout_exception(sync_e):
                            sync_err = ModelStreamError(
                                code="TIMEOUT",
                                category="TIMEOUT",
                                safe_message=f"TIMEOUT: Synchronous degradation call to '{cand_provider}' timed out.",
                                retryable=True,
                                http_status=408,
                            )
                            internal_code = ProviderErrorCode.TIMEOUT
                        elif is_network_exception(sync_e):
                            sync_err = ModelStreamError(
                                code="NETWORK_ERROR",
                                category="NETWORK",
                                safe_message=f"NETWORK_ERROR: Network connection failure during synchronous degradation for '{cand_provider}'.",
                                retryable=True,
                                http_status=None,
                            )
                            internal_code = ProviderErrorCode.NETWORK_ERROR
                        else:
                            sync_err = ModelStreamError(
                                code="STREAM_INTERNAL_ERROR",
                                category="INTERNAL",
                                safe_message=f"STREAM_INTERNAL_ERROR: Internal model invocation failure on '{cand_provider}'.",
                                retryable=False,
                                http_status=None,
                            )
                            internal_code = None

                        if internal_code is not None:
                            self.config_service.record_error(cand_provider, internal_code)
                            self.update_provider_health(cand_provider, ProviderHealth.UNAVAILABLE, detail=sync_err.safe_message)
                        last_error = sync_err
                        last_error_provider = cand_provider
                        last_error_model = cand_model
                        if strict_model_pin or len(candidates) == 1:
                            yield normalize_public_stream_delta(
                                StreamDelta(content="", finish_reason="error", error=sync_err),
                                cand_provider,
                                cand_model,
                            )
                            return
                        continue
'''

old_count = text.count(old)
new_count = text.count(new)
if old_count == 1 and new_count == 0:
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("applied production patch")
elif old_count == 0 and new_count == 1:
    print("production patch already present")
else:
    raise SystemExit(f"fail-closed: old_count={old_count}, new_count={new_count}")
