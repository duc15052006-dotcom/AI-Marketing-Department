"""One-shot hardening for raw exception leakage across public/runtime boundaries."""
from pathlib import Path


def replace(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old in text:
        text = text.replace(old, new, 1)
        p.write_text(text, encoding="utf-8")
        return
    if new not in text:
        raise RuntimeError(f"{path}: boundary drift: {old[:100]!r}")


replace(
    "runtime/engine.py",
    '''                    except Exception as exc:\n                        raise RuntimeError(\n                            f"RUN_PINNED_MODEL_CONFIGURATION_INVALID: Provider registry snapshot failed: {exc}"\n                        ) from exc\n''',
    '''                    except Exception as exc:\n                        logger.error(\n                            "Provider registry snapshot failed at run boundary (%s)",\n                            type(exc).__name__,\n                        )\n                        raise RuntimeError("RUN_PINNED_MODEL_CONFIGURATION_INVALID") from exc\n''',
)

replace(
    "runtime/engine.py",
    '''        except Exception as audit_err:\n            audit_res = self._fail_closed_audit("AUDIT_GATE_ERROR", str(audit_err))\n''',
    '''        except Exception as audit_err:\n            logger.error("Final authorization audit failed internally (%s)", type(audit_err).__name__)\n            audit_res = self._fail_closed_audit(\n                "AUDIT_GATE_ERROR",\n                "Authorization audit failed internally; deployment blocked.",\n            )\n''',
)

replace(
    "runtime/queue.py",
    '''            except Exception as e:\n                with self._lock:\n                    item.status = RunQueueStatus.FAILED\n                    item.error = str(e)\n                    item.completed_at = datetime.now(timezone.utc)\n''',
    '''            except Exception as e:\n                logger.error("Queued run %s failed at runtime boundary (%s)", item.run_id, type(e).__name__)\n                with self._lock:\n                    item.status = RunQueueStatus.FAILED\n                    item.error = "RUNTIME_INTERNAL_ERROR"\n                    item.completed_at = datetime.now(timezone.utc)\n''',
)

replace(
    "chat/engine.py",
    '''            except Exception as ex:\n                logger.warning(f"Error querying session knowledge: {ex}")\n''',
    '''            except Exception as ex:\n                logger.warning("Session knowledge lookup failed (%s)", type(ex).__name__)\n''',
)
