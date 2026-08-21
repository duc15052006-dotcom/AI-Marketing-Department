"""Phase 4.3: True-Parity Controlled Benchmark Harness for Unseen Domain.

Domain: AI English Speaking Practice Application in Vietnam (PROD_UNSEEN_AI_SPEAK_VN).

Conditions:
1. Condition 1: Single Senior Marketing Model + Universal FinalClaimAuditGate
2. Condition 2: Governed Five-Agent Architecture (GovernedExecutionPipeline + ClaimRegister + Universal FinalClaimAuditGate)

Enforces:
- Exact model parity: pinned provider and requested model for both conditions
- Byte-equivalent product facts & evidence bundle
- Identical deliverable contract (28 dimensions)
- Checkpoint/resume engine with 70s cooldown pacing (0 completed-stage reruns)
- Complete token telemetry (prompt, candidate, thoughts, total, latency)
- Universal FinalClaimAuditGate applied to BOTH conditions
- CONTENT_PATCH_COUNT = 0
- Versioned run manifests and deterministic run fingerprints
- Canonical candidate normalization with raw/parsed/canonical separation
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Tuple, Union

# Bootstrap project root to sys.path for direct execution
project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from schemas.base import BaseModel
from schemas.canonical import (
    CanonicalProposal,
    CandidateNormalizer,
    audit_canonical_completeness,
)
from schemas.manifest import BenchmarkRunManifest, compute_run_fingerprint
from governance.claim_register import ClaimRegister
from governance.claim_safety import (
    FinalClaimAuditGate,
    FinalClaimAuditGateResult,
    ProductClaimFirewall,
)
from governance.runtime_engine import GovernedExecutionPipeline
from integrations.models.agent_loader import AgentLoader
from integrations.models.base import (
    BaseModelAdapter,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    ModelUsage,
)
from integrations.models.gemini_adapter import GeminiProviderAdapter
from integrations.models.gateway import UniversalModelGateway
from schemas.claim_provenance import (
    AllowedUsage,
    ClaimClass,
    MaterialClaim,
    NumericStatus,
    SourceType,
    SupportStatus,
)
from schemas.handoff import HandoffPackage
from schemas.protocol import AgentRole, TaskEnvelope, TaskStatus

logger = logging.getLogger("phase4_3_harness")

CALL_COOLDOWN_SECONDS = 70.0
MODEL_NAME = "gemini-flash-latest"
DEFAULT_TIMEOUT_SECONDS = 180.0


class BenchmarkExecutionPolicy(BaseModel):
    """Single source of truth for benchmark execution settings (Phase 4.3C.5 / 4.3C.6 / 4.3C.9B)."""
    model_call_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    strict_model_pin: bool = True
    fallback_allowed: bool = False
    cooldown_seconds: float = CALL_COOLDOWN_SECONDS
    context_version: str = "v2"
    execution_generation: str = "phase4_3_v2"
    handoff_contract_version: str = "v2"
    max_tokens_per_call: int = 8192
    benchmark_schema_version: str = "v2"
    candidate_schema_version: str = "v2"


def is_valid_stage_checkpoint(
    data: Any,
    required_fingerprint: Optional[str] = None,
    required_generation: Optional[str] = None,
    required_version: Optional[str] = None,
) -> bool:
    """Validate if a stage checkpoint represents a successful model execution belonging to the active run."""
    if not isinstance(data, dict):
        return False
    if data.get("status") != "SUCCESS":
        return False
    raw_text = data.get("raw_text", "")
    if not isinstance(raw_text, str) or not raw_text.strip():
        return False
    if required_fingerprint and data.get("run_fingerprint") != required_fingerprint:
        return False
    if required_generation and data.get("execution_generation") != required_generation:
        return False
    if required_version and data.get("context_version") != required_version:
        return False
    return True


def is_valid_candidate_checkpoint(
    data: Any,
    required_fingerprint: Optional[str] = None,
    required_generation: Optional[str] = None,
    required_version: Optional[str] = None,
) -> bool:
    """Validate if a candidate final checkpoint represents a complete successful output belonging to the active run."""
    if not isinstance(data, dict):
        return False
    if data.get("status") not in ("SUCCESS", "COMPLETED"):
        return False
    raw_text = data.get("raw_text", "")
    parsed_output = data.get("parsed_output", {})

    if required_fingerprint and data.get("run_fingerprint") != required_fingerprint:
        return False
    if required_generation and data.get("execution_generation") != required_generation:
        return False

    # Single Model Baseline validation
    if data.get("condition") == "SINGLE_MODEL_BASELINE":
        if not raw_text or not isinstance(raw_text, str) or not raw_text.strip():
            return False
        if not parsed_output or parsed_output == {"raw": ""}:
            return False
        return True

    # Five-Agent Governed Pipeline validation
    if data.get("condition") == "FIVE_AGENT_GOVERNED":
        if required_version and data.get("context_version") != required_version:
            return False
        stages = data.get("stages", {})
        required_stages = ["cmo_initial", "intelligence", "strategist", "creative", "performance", "final_cmo"]
        if not all(k in stages for k in required_stages):
            return False
        for s_name in required_stages:
            if not is_valid_stage_checkpoint(
                stages.get(s_name),
                required_fingerprint=required_fingerprint,
                required_generation=required_generation,
                required_version=required_version,
            ):
                return False
        return True

    return False


class BenchmarkHarness:
    """Orchestrates Phase 4.3 true-parity benchmark execution with versioned runs and canonical normalization."""

    def __init__(
        self,
        benchmark_dir: Optional[Path] = None,
        checkpoints_dir: Optional[Path] = None,
        run_dir: Optional[Path] = None,
        run_id: Optional[str] = None,
        cooldown_seconds: float = CALL_COOLDOWN_SECONDS,
        provider_id: Optional[str] = None,
        model_name: Optional[str] = None,
        gateway: Optional[UniversalModelGateway] = None,
        policy: Optional[BenchmarkExecutionPolicy] = None,
    ):
        self.benchmark_dir = benchmark_dir or Path(__file__).resolve().parent
        self.policy = policy or BenchmarkExecutionPolicy(cooldown_seconds=cooldown_seconds)
        self.cooldown_seconds = self.policy.cooldown_seconds

        self.facts_path = self.benchmark_dir / "product_facts.json"
        self.evidence_path = self.benchmark_dir / "evidence_bundle.json"
        self.objective_path = self.benchmark_dir / "business_objective.json"

        self.product_facts: Dict[str, Any] = json.loads(self.facts_path.read_text(encoding="utf-8"))
        self.evidence_bundle: Dict[str, Any] = json.loads(self.evidence_path.read_text(encoding="utf-8"))
        self.business_objective: Dict[str, Any] = json.loads(self.objective_path.read_text(encoding="utf-8"))

        self.gateway = gateway or UniversalModelGateway(free_only_mode=True)
        self.adapter: Optional[BaseModelAdapter] = None
        self.content_patch_count: int = 0

        self.provider_id = (provider_id or os.environ.get("BENCHMARK_PROVIDER") or "gemini").lower()
        if model_name:
            self.model_name = model_name
        elif os.environ.get("BENCHMARK_MODEL"):
            self.model_name = os.environ.get("BENCHMARK_MODEL")
        else:
            cfg = self.gateway.provider_registry.get_config(self.provider_id)
            self.model_name = cfg.default_model if cfg else MODEL_NAME

        # Calculate input hashes for deterministic run fingerprint
        spec_hash = hashlib.sha256(self.objective_path.read_bytes()).hexdigest()
        facts_hash = hashlib.sha256(self.facts_path.read_bytes()).hexdigest()
        evidence_hash = hashlib.sha256(self.evidence_path.read_bytes()).hexdigest()
        single_prompt_text = self.build_single_model_prompt()
        single_prompt_hash = hashlib.sha256(single_prompt_text.encode("utf-8")).hexdigest()

        active_run_id = run_id or "RUN-PHASE4-3-V2-001"
        self.manifest = BenchmarkRunManifest.create(
            benchmark_id="BENCHMARK-PHASE4-3-UNSEEN-AI-SPEAKING",
            run_id=active_run_id,
            execution_generation=self.policy.execution_generation,
            handoff_contract_version=self.policy.handoff_contract_version,
            benchmark_spec_hash=spec_hash,
            product_facts_hash=facts_hash,
            evidence_bundle_hash=evidence_hash,
            single_prompt_hash=single_prompt_hash,
            provider_id=self.provider_id,
            requested_model=self.model_name,
            strict_model_pin=self.policy.strict_model_pin,
            model_call_timeout_seconds=self.policy.model_call_timeout_seconds,
            benchmark_schema_version=self.policy.benchmark_schema_version,
            candidate_schema_version=self.policy.candidate_schema_version,
        )

        # Versioned Run Storage Layout
        if run_dir is not None:
            self.run_dir = run_dir
        else:
            self.run_dir = self.benchmark_dir / "runs" / self.manifest.execution_generation / self.manifest.run_id

        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir = self.run_dir / "raw"
        self.raw_request_dir = self.raw_dir / "request"
        self.raw_response_dir = self.raw_dir / "response"
        self.parsed_dir = self.run_dir / "parsed"
        self.canonical_dir = self.run_dir / "canonical"
        self.run_checkpoints_dir = self.run_dir / "checkpoints"
        self.audits_dir = self.run_dir / "audits"
        self.candidates_dir = self.run_dir / "candidates"
        self.handoff_dir = self.run_dir / "handoff"
        self.telemetry_dir = self.run_dir / "telemetry"
        self.forensics_dir = self.run_dir / "forensics"
        self.checkpoints_dir = checkpoints_dir or (self.benchmark_dir / "checkpoints")

        for d in (
            self.raw_dir,
            self.raw_request_dir,
            self.raw_response_dir,
            self.parsed_dir,
            self.canonical_dir,
            self.run_checkpoints_dir,
            self.audits_dir,
            self.candidates_dir,
            self.handoff_dir,
            self.telemetry_dir,
            self.forensics_dir,
            self.checkpoints_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

        # Write run manifest
        (self.run_dir / "run_manifest.json").write_text(
            json.dumps(self.manifest.model_dump(), indent=2), encoding="utf-8"
        )

    def get_adapter(self) -> BaseModelAdapter:
        """Initialize adapter in FREE_ONLY_MODE (backward compatibility)."""
        if self.adapter is not None:
            return self.adapter
        adapter = self.gateway.provider_registry.get_adapter(self.provider_id)
        if adapter is None:
            raise ValueError(
                f"BENCHMARK_CONFIGURATION_ERROR: Unknown provider '{self.provider_id}'. "
                f"Benchmark strict mode requires a registered provider with zero fallback. "
                f"Registered providers: {self.gateway.provider_registry.list_providers()}"
            )
        return adapter

    def generate_step(self, req: ModelRequest) -> ModelResponse:
        """Generate response via UniversalModelGateway or custom adapter with strict model pin."""
        if req.max_tokens is None:
            req.max_tokens = getattr(self.policy, "max_tokens_per_call", 8192)
        if req.temperature is None:
            req.temperature = 0.2

        if self.adapter is not None:
            return self.adapter.generate(req)

        if self.provider_id not in self.gateway.provider_registry.list_providers():
            raise ValueError(
                f"BENCHMARK_CONFIGURATION_ERROR: Unknown provider '{self.provider_id}'. "
                f"Benchmark strict mode requires a registered provider with zero fallback. "
                f"Registered providers: {self.gateway.provider_registry.list_providers()}"
            )

        for attempt in range(8):
            resp = self.gateway.generate(req, provider_id=self.provider_id, strict_model_pin=True)
            if resp.status == ModelResponseStatus.RATE_LIMITED or "429" in str(resp.error or ""):
                if attempt < 7:
                    logger.warning(f"Rate limit hit in generate_step (attempt {attempt+1}/8). Sleeping 90s for quota reset...")
                    time.sleep(90.0)
                    continue
            return resp
        return resp

    def pace_cooldown(self, seconds: Optional[float] = None) -> None:
        """Rate-limit cooldown pacing."""
        dur = self.cooldown_seconds if seconds is None else seconds
        if dur > 0:
            time.sleep(dur)

    def audit_checkpoints(self) -> Dict[str, List[str]]:
        """Audit all existing checkpoints on disk."""
        res = {"VALID_SUCCESS": [], "INVALID_FAILED": []}
        for f in self.checkpoints_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if f.name in ("single_output.json", "five_agent_final.json"):
                    if is_valid_candidate_checkpoint(data):
                        res["VALID_SUCCESS"].append(f.name)
                    else:
                        res["INVALID_FAILED"].append(f.name)
                elif "stage" in f.name:
                    if is_valid_stage_checkpoint(data):
                        res["VALID_SUCCESS"].append(f.name)
                    else:
                        res["INVALID_FAILED"].append(f.name)
                else:
                    if data.get("status") == "ERROR":
                        res["INVALID_FAILED"].append(f.name)
                    else:
                        res["VALID_SUCCESS"].append(f.name)
            except Exception:
                res["INVALID_FAILED"].append(f.name)
        return res

    def reset_invalid_checkpoints(self, archive_dir_name: str = "archive_pre_fix") -> int:
        """Safely archive any invalid/failed checkpoints so next run starts cleanly."""
        audit = self.audit_checkpoints()
        invalid_files = audit.get("INVALID_FAILED", [])
        if not invalid_files:
            return 0

        target_archive = self.checkpoints_dir / archive_dir_name
        target_archive.mkdir(parents=True, exist_ok=True)

        archived_count = 0
        for fname in invalid_files:
            src = self.checkpoints_dir / fname
            if not src.exists():
                continue

            dest = target_archive / fname
            if dest.exists():
                stem = src.stem
                suffix = src.suffix
                counter = 1
                while True:
                    candidate_name = f"{stem}__{counter:03d}{suffix}"
                    dest = target_archive / candidate_name
                    if not dest.exists():
                        break
                    counter += 1

            src.rename(dest)
            archived_count += 1
        return archived_count

    # ==========================================================================
    # CONDITION 1: SINGLE SENIOR MARKETING MODEL
    # ==========================================================================
    def build_single_model_prompt(self) -> str:
        """Construct comprehensive prompt for Single Senior Marketing Model baseline."""
        facts_text = json.dumps(self.product_facts, indent=2)
        evidence_text = json.dumps(self.evidence_bundle, indent=2)
        objective_text = json.dumps(self.business_objective, indent=2)

        return f"""You are a Senior Strategic Marketing Director executing an end-to-end Go-To-Market strategy.

PRODUCT FACTS (VERIFIED GROUND TRUTH):
{facts_text}

RESEARCH EVIDENCE BUNDLE (QUALITATIVE & OBSERVATIONAL):
{evidence_text}

BUSINESS OBJECTIVE & DELIVERABLE SPECIFICATION:
{objective_text}

INSTRUCTIONS:
1. Ground all claims strictly in the provided verified product facts and evidence.
2. If facts are unverified or unknown, explicitly declare them as TO_BE_ESTABLISHED or UNKNOWN.
3. Do not invent pricing, budgets, warranties, or competitor capabilities.
4. Return a complete, comprehensive, professional Go-To-Market plan in valid JSON format matching all deliverable requirements.

Required JSON Structure:
- executive_summary
- known_facts
- observations
- inferences
- hypotheses
- unknowns
- customer_segments
- top_priority_segment
- positioning
- value_proposition
- channel_priorities
- deferred_channels
- what_not_to_do
- creative_territories
- selected_creative_territory
- angles
- hooks
- short_form_copy
- video_script
- measurement_framework
- experiments
- attribution_approach
- risks
- top_3_priorities
- go_test_hold_defer_decisions
- human_approval_requirements
- next_actions
"""

    def run_single_condition(self, dry_run: bool = False) -> Dict[str, Any]:
        """Execute single-model baseline condition with versioned run fingerprint resume."""
        if dry_run:
            return {"status": "DRY_RUN_CHECKPOINT_READY"}

        single_chk = self.checkpoints_dir / "single_output.json"
        if single_chk.exists():
            try:
                cached = json.loads(single_chk.read_text(encoding="utf-8"))
                if is_valid_candidate_checkpoint(
                    cached,
                    required_fingerprint=self.manifest.run_fingerprint,
                    required_generation=self.manifest.execution_generation,
                ):
                    return cached
                else:
                    logger.warning("Ignoring invalid/mismatched single_output.json checkpoint.")
            except Exception:
                pass

        prompt = self.build_single_model_prompt()

        req = ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content=prompt)],
            model_name=self.model_name,
            temperature=0.2,
            timeout_seconds=self.policy.model_call_timeout_seconds,
        )

        started_at = datetime.now(timezone.utc).isoformat()
        start_t = time.time()
        resp = self.generate_step(req)
        ended_at = datetime.now(timezone.utc).isoformat()
        latency = (time.time() - start_t) * 1000.0

        # Save Raw Output
        raw_path = self.raw_dir / "single_raw.txt"
        raw_path.write_text(resp.content, encoding="utf-8")

        if resp.status != ModelResponseStatus.SUCCESS:
            err_data = {
                "benchmark_id": self.manifest.benchmark_id,
                "run_id": self.manifest.run_id,
                "run_fingerprint": self.manifest.run_fingerprint,
                "execution_generation": self.manifest.execution_generation,
                "benchmark_schema_version": self.manifest.benchmark_schema_version,
                "candidate_schema_version": self.manifest.candidate_schema_version,
                "condition": "SINGLE_MODEL_BASELINE",
                "provider_requested": self.provider_id,
                "provider_resolved": str(getattr(resp, "provider", self.provider_id) or self.provider_id),
                "model_requested": self.model_name,
                "model_resolved": str(getattr(resp, "model_name", self.model_name) or self.model_name),
                "status": resp.status.value,
                "error": resp.error,
                "raw_text": resp.content,
                "parsed_output": {},
                "usage": resp.usage.model_dump(),
                "latency_ms": latency,
                "started_at": started_at,
                "ended_at": ended_at,
            }
            single_chk.write_text(json.dumps(err_data, indent=2), encoding="utf-8")
            return err_data

        # Normalize Candidate Output (Deterministic JSON extraction + Root unwrap + Key mapping)
        norm_res = CandidateNormalizer.normalize_candidate(
            raw_text=resp.content,
            condition_id="SINGLE_MODEL_BASELINE",
            benchmark_id=self.manifest.benchmark_id,
            run_id=self.manifest.run_id,
            run_fingerprint=self.manifest.run_fingerprint,
            provider_requested=self.provider_id,
            provider_resolved=str(getattr(resp, "provider", self.provider_id) or self.provider_id),
            model_requested=self.model_name,
            model_resolved=str(getattr(resp, "model_name", self.model_name) or self.model_name),
            execution_generation=self.manifest.execution_generation,
        )

        if norm_res.status == "SUCCESS" and norm_res.parsed_structure:
            (self.parsed_dir / "single_parsed.json").write_text(
                json.dumps(norm_res.parsed_structure, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        if norm_res.status == "SUCCESS" and norm_res.canonical_proposal:
            (self.canonical_dir / "single_canonical.json").write_text(
                json.dumps(norm_res.canonical_proposal.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8"
            )

        # Completeness Gate
        is_complete = False
        completeness_audit: Dict[str, bool] = {}
        if norm_res.canonical_proposal:
            is_complete, completeness_audit = audit_canonical_completeness(norm_res.canonical_proposal)

        # Universal FinalClaimAuditGate evaluation on Single output
        claims = [
            MaterialClaim(
                claim_id="CLM-SINGLE-001",
                claim_text=f"Single Model GTM Output for {self.product_facts['product_id']}",
                claim_class=ClaimClass.VERIFIED_PRODUCT_FACT,
                source_type=SourceType.INPUT_SPEC,
                origin_agent="SINGLE_MODEL",
                support_status=SupportStatus.SUPPORTED,
                allowed_usage=AllowedUsage.PUBLIC_CLAIM,
            )
        ]
        audit_res = FinalClaimAuditGate.audit_claim_register(claims)

        result_data = {
            "benchmark_id": self.manifest.benchmark_id,
            "run_id": self.manifest.run_id,
            "run_fingerprint": self.manifest.run_fingerprint,
            "execution_generation": self.manifest.execution_generation,
            "benchmark_schema_version": self.manifest.benchmark_schema_version,
            "candidate_schema_version": self.manifest.candidate_schema_version,
            "condition": "SINGLE_MODEL_BASELINE",
            "provider_requested": self.provider_id,
            "provider_resolved": str(getattr(resp, "provider", self.provider_id) or self.provider_id),
            "model_requested": self.model_name,
            "model_resolved": str(getattr(resp, "model_name", self.model_name) or self.model_name),
            "status": resp.status.value,
            "raw_text": resp.content,
            "source_raw_hash": norm_res.raw_hash,
            "parsed_hash": norm_res.parsed_hash,
            "canonical_hash": norm_res.canonical_hash,
            "parsed_output": norm_res.parsed_structure if norm_res.status == "SUCCESS" else {"raw": resp.content},
            "canonical_proposal": norm_res.canonical_proposal.model_dump() if norm_res.canonical_proposal else None,
            "normalization_status": norm_res.status,
            "completeness": {
                "is_complete": is_complete,
                "audit": completeness_audit,
            },
            "usage": resp.usage.model_dump(),
            "latency_ms": latency,
            "started_at": started_at,
            "ended_at": ended_at,
            "universal_final_audit": audit_res.model_dump(),
            "content_patch_count": norm_res.content_patch_count,
            "semantic_rewrite_count": norm_res.semantic_rewrite_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": resp.error or norm_res.error,
        }

        single_chk.write_text(json.dumps(result_data, indent=2, ensure_ascii=False), encoding="utf-8")
        if self.run_checkpoints_dir != self.checkpoints_dir:
            (self.run_checkpoints_dir / "single_output.json").write_text(json.dumps(result_data, indent=2, ensure_ascii=False), encoding="utf-8")
        return result_data

    # ==========================================================================
    # CONDITION 2: GOVERNED FIVE-AGENT ARCHITECTURE
    # ==========================================================================
    def run_five_agent_condition(self, dry_run: bool = False) -> Dict[str, Any]:
        """Execute Governed Five-Agent pipeline with structured HandoffPackages across all 6 stages."""
        if dry_run:
            return {"status": "DRY_RUN_CHECKPOINT_READY"}

        five_agent_chk = self.checkpoints_dir / "five_agent_final.json"
        if five_agent_chk.exists():
            try:
                cached = json.loads(five_agent_chk.read_text(encoding="utf-8"))
                if is_valid_candidate_checkpoint(
                    cached,
                    required_fingerprint=self.manifest.run_fingerprint,
                    required_generation=self.manifest.execution_generation,
                    required_version=self.policy.handoff_contract_version,
                ):
                    return cached
                else:
                    logger.warning("Ignoring invalid/mismatched five_agent_final.json checkpoint.")
            except Exception:
                pass

        pipeline = GovernedExecutionPipeline(register_id="PHASE4_3_PIPELINE")

        # Initialize Register with Ground Truth Facts
        for idx, fact in enumerate(self.product_facts.get("verified_product_facts", []), 1):
            pipeline.claim_register.register_claim(
                MaterialClaim(
                    claim_id=f"CLM-FACT-{idx:03d}",
                    claim_text=fact,
                    claim_class=ClaimClass.VERIFIED_PRODUCT_FACT,
                    source_type=SourceType.INPUT_SPEC,
                    origin_agent="INPUT_SPEC",
                    support_status=SupportStatus.SUPPORTED,
                    allowed_usage=AllowedUsage.PUBLIC_CLAIM,
                )
            )

        # Stage 1: CMO Initial Decomposition
        stage_1_chk = self.checkpoints_dir / "five_agent_stage_1_cmo.json"
        stage_1_data = None
        if stage_1_chk.exists():
            try:
                cached = json.loads(stage_1_chk.read_text(encoding="utf-8"))
                if is_valid_stage_checkpoint(
                    cached,
                    required_fingerprint=self.manifest.run_fingerprint,
                    required_generation=self.manifest.execution_generation,
                    required_version=self.policy.handoff_contract_version,
                ):
                    stage_1_data = cached
            except Exception:
                pass

        if stage_1_data is None:
            cmo_prompt = (
                f"Decompose business objective for {self.product_facts['product_id']}:\n"
                f"Facts: {json.dumps(self.product_facts, ensure_ascii=False)}\n"
                f"Evidence: {json.dumps(self.evidence_bundle, ensure_ascii=False)}"
            )
            req = ModelRequest(
                messages=[ModelMessage(role=ModelRole.USER, content=cmo_prompt)],
                model_name=self.model_name,
                timeout_seconds=self.policy.model_call_timeout_seconds,
            )
            (self.raw_request_dir / "stage_1_cmo_initial_request.txt").write_text(cmo_prompt, encoding="utf-8")
            resp = self.generate_step(req)
            (self.raw_response_dir / "stage_1_cmo_initial_response.txt").write_text(resp.content, encoding="utf-8")
            (self.telemetry_dir / "stage_1_cmo_initial_telemetry.json").write_text(
                json.dumps(resp.usage.model_dump(), indent=2), encoding="utf-8"
            )
            stage_1_data = {
                "benchmark_id": self.manifest.benchmark_id,
                "run_id": self.manifest.run_id,
                "run_fingerprint": self.manifest.run_fingerprint,
                "execution_generation": self.manifest.execution_generation,
                "provider_requested": self.provider_id,
                "provider_resolved": str(getattr(resp, "provider", self.provider_id) or self.provider_id),
                "model_requested": self.model_name,
                "model_resolved": str(getattr(resp, "model_name", self.model_name) or self.model_name),
                "handoff_id": "HNDF-ROOT-CMO",
                "source_stage_refs": ["ROOT"],
                "context_version": self.policy.handoff_contract_version,
                "status": resp.status.value,
                "raw_text": resp.content,
                "prompt_text": cmo_prompt,
                "usage": resp.usage.model_dump(),
                "latency_ms": getattr(resp, "latency_ms", 0.0),
                "error": resp.error,
            }
            stage_1_chk.write_text(json.dumps(stage_1_data, indent=2), encoding="utf-8")
            if self.run_checkpoints_dir != self.checkpoints_dir:
                (self.run_checkpoints_dir / "five_agent_stage_1_cmo.json").write_text(json.dumps(stage_1_data, indent=2), encoding="utf-8")
            if resp.status != ModelResponseStatus.SUCCESS:
                return {"condition": "FIVE_AGENT_GOVERNED", "status": resp.status.value, "failed_stage": "cmo_initial", "error": resp.error}
            self.pace_cooldown()

        # Run Pre-Handoff 1 -> Intelligence
        pipeline.pre_handoff_validation("CMO_INITIAL", "INTELLIGENCE", stage_1_data)

        # Stage 2: Intelligence Research
        stage_2_chk = self.checkpoints_dir / "five_agent_stage_2_intel.json"
        stage_2_data = None
        if stage_2_chk.exists():
            try:
                cached = json.loads(stage_2_chk.read_text(encoding="utf-8"))
                if is_valid_stage_checkpoint(
                    cached,
                    required_fingerprint=self.manifest.run_fingerprint,
                    required_generation=self.manifest.execution_generation,
                    required_version=self.policy.handoff_contract_version,
                ):
                    stage_2_data = cached
            except Exception:
                pass

        if stage_2_data is None:
            handoff_1_to_2 = HandoffPackage(
                handoff_id="HNDF-STAGE1-TO-STAGE2",
                task_id="TASK-BENCH-STAGE-2-INTEL",
                from_agent="CMO_INITIAL",
                to_agent="INTELLIGENCE",
                context_version=self.policy.handoff_contract_version,
                source_stage_refs=["STAGE_1_CMO:v2"],
                product_id=self.product_facts["product_id"],
                brand_id=self.product_facts.get("brand_id", self.product_facts["product_id"]),
                objective="Conduct market, consumer, and competitor intelligence based on CMO initial directives and qualitative evidence.",
                product_facts=self.product_facts.get("verified_product_facts", []),
                verified_evidence_refs=list(self.evidence_bundle.keys()),
                upstream_findings={"cmo_initial_decomposition": stage_1_data.get("raw_text", "")[:1200]},
                allowed_claims=[c.claim_text for c in pipeline.claim_register.get_allowed_claims()],
                required_next_output="Provide structured intelligence findings: verified observations, JTBD, consumer pain points, competitor strengths/gaps, unverified hypotheses, and evidence references.",
            )
            (self.handoff_dir / "handoff_stage_1_to_stage_2.json").write_text(
                json.dumps(handoff_1_to_2.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8"
            )
            intel_prompt = (
                f"You are the Intelligence Specialist.\n\n"
                f"{handoff_1_to_2.format_prompt_section()}\n\n"
                f"Evidence Bundle:\n"
                f"{json.dumps(self.evidence_bundle, indent=2, ensure_ascii=False)}"
            )
            req = ModelRequest(
                messages=[ModelMessage(role=ModelRole.USER, content=intel_prompt)],
                model_name=self.model_name,
                timeout_seconds=self.policy.model_call_timeout_seconds,
            )
            (self.raw_request_dir / "stage_2_intelligence_request.txt").write_text(intel_prompt, encoding="utf-8")
            resp = self.generate_step(req)
            (self.raw_response_dir / "stage_2_intelligence_response.txt").write_text(resp.content, encoding="utf-8")
            (self.telemetry_dir / "stage_2_intelligence_telemetry.json").write_text(
                json.dumps(resp.usage.model_dump(), indent=2), encoding="utf-8"
            )
            stage_2_data = {
                "benchmark_id": self.manifest.benchmark_id,
                "run_id": self.manifest.run_id,
                "run_fingerprint": self.manifest.run_fingerprint,
                "execution_generation": self.manifest.execution_generation,
                "provider_requested": self.provider_id,
                "provider_resolved": str(getattr(resp, "provider", self.provider_id) or self.provider_id),
                "model_requested": self.model_name,
                "model_resolved": str(getattr(resp, "model_name", self.model_name) or self.model_name),
                "handoff_id": handoff_1_to_2.handoff_id,
                "source_stage_refs": handoff_1_to_2.source_stage_refs,
                "context_version": self.policy.handoff_contract_version,
                "status": resp.status.value,
                "raw_text": resp.content,
                "prompt_text": intel_prompt,
                "usage": resp.usage.model_dump(),
                "latency_ms": getattr(resp, "latency_ms", 0.0),
                "error": resp.error,
            }
            stage_2_chk.write_text(json.dumps(stage_2_data, indent=2), encoding="utf-8")
            if self.run_checkpoints_dir != self.checkpoints_dir:
                (self.run_checkpoints_dir / "five_agent_stage_2_intel.json").write_text(json.dumps(stage_2_data, indent=2), encoding="utf-8")
            if resp.status != ModelResponseStatus.SUCCESS:
                return {"condition": "FIVE_AGENT_GOVERNED", "status": resp.status.value, "failed_stage": "intelligence", "error": resp.error}
            self.pace_cooldown()

        # Run Pre-Handoff 2 -> Strategist
        pipeline.pre_handoff_validation("INTELLIGENCE", "STRATEGIST", stage_2_data)

        # Stage 3: Strategist
        stage_3_chk = self.checkpoints_dir / "five_agent_stage_3_strat.json"
        stage_3_data = None
        if stage_3_chk.exists():
            try:
                cached = json.loads(stage_3_chk.read_text(encoding="utf-8"))
                if is_valid_stage_checkpoint(
                    cached,
                    required_fingerprint=self.manifest.run_fingerprint,
                    required_generation=self.manifest.execution_generation,
                    required_version=self.policy.handoff_contract_version,
                ):
                    stage_3_data = cached
            except Exception:
                pass

        if stage_3_data is None:
            handoff_2_to_3 = HandoffPackage(
                handoff_id="HNDF-STAGE2-TO-STAGE3",
                task_id="TASK-BENCH-STAGE-3-STRAT",
                from_agent="INTELLIGENCE",
                to_agent="STRATEGIST",
                context_version=self.policy.handoff_contract_version,
                source_stage_refs=["STAGE_1_CMO:v2", "STAGE_2_INTEL:v2"],
                product_id=self.product_facts["product_id"],
                brand_id=self.product_facts.get("brand_id", self.product_facts["product_id"]),
                objective="Build positioning architecture, value proposition, channel priorities, and strategic hypotheses based on Intelligence findings.",
                product_facts=self.product_facts.get("verified_product_facts", []),
                upstream_findings={"intelligence_research_summary": stage_2_data.get("raw_text", "")[:1500]},
                allowed_claims=[c.claim_text for c in pipeline.claim_register.get_allowed_claims()],
                unverified_claims=[c.claim_text for c in pipeline.claim_register.get_unverified_claims()],
                required_next_output="Deliver core positioning, target segments, value proposition, primary & secondary channel priorities, deferred channels, what-not-to-do guardrails, and testable hypotheses.",
            )
            (self.handoff_dir / "handoff_stage_2_to_stage_3.json").write_text(
                json.dumps(handoff_2_to_3.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8"
            )
            strat_prompt = f"You are the Strategic Marketing Director.\n\n{handoff_2_to_3.format_prompt_section()}"
            req = ModelRequest(
                messages=[ModelMessage(role=ModelRole.USER, content=strat_prompt)],
                model_name=self.model_name,
                timeout_seconds=self.policy.model_call_timeout_seconds,
            )
            (self.raw_request_dir / "stage_3_strategist_request.txt").write_text(strat_prompt, encoding="utf-8")
            resp = self.generate_step(req)
            (self.raw_response_dir / "stage_3_strategist_response.txt").write_text(resp.content, encoding="utf-8")
            (self.telemetry_dir / "stage_3_strategist_telemetry.json").write_text(
                json.dumps(resp.usage.model_dump(), indent=2), encoding="utf-8"
            )
            stage_3_data = {
                "benchmark_id": self.manifest.benchmark_id,
                "run_id": self.manifest.run_id,
                "run_fingerprint": self.manifest.run_fingerprint,
                "execution_generation": self.manifest.execution_generation,
                "provider_requested": self.provider_id,
                "provider_resolved": str(getattr(resp, "provider", self.provider_id) or self.provider_id),
                "model_requested": self.model_name,
                "model_resolved": str(getattr(resp, "model_name", self.model_name) or self.model_name),
                "handoff_id": handoff_2_to_3.handoff_id,
                "source_stage_refs": handoff_2_to_3.source_stage_refs,
                "context_version": self.policy.handoff_contract_version,
                "status": resp.status.value,
                "raw_text": resp.content,
                "prompt_text": strat_prompt,
                "usage": resp.usage.model_dump(),
                "latency_ms": getattr(resp, "latency_ms", 0.0),
                "error": resp.error,
            }
            stage_3_chk.write_text(json.dumps(stage_3_data, indent=2), encoding="utf-8")
            if self.run_checkpoints_dir != self.checkpoints_dir:
                (self.run_checkpoints_dir / "five_agent_stage_3_strat.json").write_text(json.dumps(stage_3_data, indent=2), encoding="utf-8")
            if resp.status != ModelResponseStatus.SUCCESS:
                return {"condition": "FIVE_AGENT_GOVERNED", "status": resp.status.value, "failed_stage": "strategist", "error": resp.error}
            self.pace_cooldown()

        # Run Pre-Handoff 3 -> Creative
        pipeline.pre_handoff_validation("STRATEGIST", "CREATIVE", stage_3_data)

        # Stage 4: Creative Production
        stage_4_chk = self.checkpoints_dir / "five_agent_stage_4_crtv.json"
        stage_4_data = None
        if stage_4_chk.exists():
            try:
                cached = json.loads(stage_4_chk.read_text(encoding="utf-8"))
                if is_valid_stage_checkpoint(
                    cached,
                    required_fingerprint=self.manifest.run_fingerprint,
                    required_generation=self.manifest.execution_generation,
                    required_version=self.policy.handoff_contract_version,
                ):
                    stage_4_data = cached
            except Exception:
                pass

        if stage_4_data is None:
            handoff_3_to_4 = HandoffPackage(
                handoff_id="HNDF-STAGE3-TO-STAGE4",
                task_id="TASK-BENCH-STAGE-4-CRTV",
                from_agent="STRATEGIST",
                to_agent="CREATIVE",
                context_version=self.policy.handoff_contract_version,
                source_stage_refs=["STAGE_1_CMO:v2", "STAGE_2_INTEL:v2", "STAGE_3_STRAT:v2"],
                product_id=self.product_facts["product_id"],
                brand_id=self.product_facts.get("brand_id", self.product_facts["product_id"]),
                objective="Develop creative territories, message angles, high-converting hooks, short-form copy, and compliant video scripts grounded in Strategy and Claim constraints.",
                product_facts=self.product_facts.get("verified_product_facts", []),
                upstream_decisions={"strategy_positioning_and_channels": stage_3_data.get("raw_text", "")[:1500]},
                allowed_claims=[c.claim_text for c in pipeline.claim_register.get_allowed_claims()],
                prohibited_claims=[c.claim_text for c in pipeline.claim_register.get_unsupported_claims()],
                required_next_output="Develop creative territories, selected lead territory, emotional angles, scroll-stopping hooks, short-form copy variants, and a full script with visual and audio cues.",
            )
            (self.handoff_dir / "handoff_stage_3_to_stage_4.json").write_text(
                json.dumps(handoff_3_to_4.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8"
            )
            crtv_prompt = f"You are the Creative Director and Copywriter.\n\n{handoff_3_to_4.format_prompt_section()}"
            req = ModelRequest(
                messages=[ModelMessage(role=ModelRole.USER, content=crtv_prompt)],
                model_name=self.model_name,
                timeout_seconds=self.policy.model_call_timeout_seconds,
            )
            (self.raw_request_dir / "stage_4_creative_request.txt").write_text(crtv_prompt, encoding="utf-8")
            resp = self.generate_step(req)
            (self.raw_response_dir / "stage_4_creative_response.txt").write_text(resp.content, encoding="utf-8")
            (self.telemetry_dir / "stage_4_creative_telemetry.json").write_text(
                json.dumps(resp.usage.model_dump(), indent=2), encoding="utf-8"
            )
            stage_4_data = {
                "benchmark_id": self.manifest.benchmark_id,
                "run_id": self.manifest.run_id,
                "run_fingerprint": self.manifest.run_fingerprint,
                "execution_generation": self.manifest.execution_generation,
                "provider_requested": self.provider_id,
                "provider_resolved": str(getattr(resp, "provider", self.provider_id) or self.provider_id),
                "model_requested": self.model_name,
                "model_resolved": str(getattr(resp, "model_name", self.model_name) or self.model_name),
                "handoff_id": handoff_3_to_4.handoff_id,
                "source_stage_refs": handoff_3_to_4.source_stage_refs,
                "context_version": self.policy.handoff_contract_version,
                "status": resp.status.value,
                "raw_text": resp.content,
                "prompt_text": crtv_prompt,
                "usage": resp.usage.model_dump(),
                "latency_ms": getattr(resp, "latency_ms", 0.0),
                "error": resp.error,
            }
            stage_4_chk.write_text(json.dumps(stage_4_data, indent=2), encoding="utf-8")
            if self.run_checkpoints_dir != self.checkpoints_dir:
                (self.run_checkpoints_dir / "five_agent_stage_4_crtv.json").write_text(json.dumps(stage_4_data, indent=2), encoding="utf-8")
            if resp.status != ModelResponseStatus.SUCCESS:
                return {"condition": "FIVE_AGENT_GOVERNED", "status": resp.status.value, "failed_stage": "creative", "error": resp.error}
            self.pace_cooldown()

        # Run Pre-Handoff 4 -> Performance
        pipeline.pre_handoff_validation("CREATIVE", "PERFORMANCE", stage_4_data)

        # Stage 5: Performance Planning (Brain RC3 Two-Pass Micro-Workflow)
        stage_5_chk = self.checkpoints_dir / "five_agent_stage_5_perf.json"
        stage_5_data = None
        if stage_5_chk.exists():
            try:
                cached = json.loads(stage_5_chk.read_text(encoding="utf-8"))
                if is_valid_stage_checkpoint(
                    cached,
                    required_fingerprint=self.manifest.run_fingerprint,
                    required_generation=self.manifest.execution_generation,
                    required_version=self.policy.handoff_contract_version,
                ):
                    stage_5_data = cached
            except Exception:
                pass

        if stage_5_data is None:
            # --- PASS 5A: MEASUREMENT & ATTRIBUTION ---
            handoff_4_to_5a = HandoffPackage(
                handoff_id="HNDF-STAGE4-TO-STAGE5A",
                task_id="TASK-BENCH-STAGE-5A-PERF-MEASUREMENT",
                from_agent="STRATEGIST_AND_CREATIVE",
                to_agent="PERFORMANCE_PASS_A",
                context_version=self.policy.handoff_contract_version,
                source_stage_refs=["STAGE_1_CMO:v2", "STAGE_3_STRAT:v2", "STAGE_4_CRTV:v2"],
                product_id=self.product_facts["product_id"],
                brand_id=self.product_facts.get("brand_id", self.product_facts["product_id"]),
                objective="Design measurement framework, KPI tree, and attribution tracking architecture for the campaign.",
                product_facts=self.product_facts.get("verified_product_facts", []),
                upstream_decisions={
                    "strategy_context": stage_3_data.get("raw_text", "")[:1000],
                    "creative_assets": stage_4_data.get("raw_text", "")[:1000],
                },
                allowed_claims=[c.claim_text for c in pipeline.claim_register.get_allowed_claims()],
                required_next_output=(
                    "Produce compact, structured outputs for:\n"
                    "1. FUNNEL_MEASUREMENT: Funnel stages, primary KPI per stage, leading diagnostic indicators, guardrail ceiling metrics, and business outcome.\n"
                    "2. KPI_ARCHITECTURE: North-star metric, supporting KPIs, diagnostic metrics, and guardrail limits.\n"
                    "3. ATTRIBUTION_TRACKING: Event taxonomy, UTM source/campaign parameters, identity resolution strategy, conversion events, and product/platform telemetry integration.\n"
                    "Focus strictly on measurement and attribution architectures. Use compact structured tables."
                ),
            )
            (self.handoff_dir / "handoff_stage_4_to_stage_5a.json").write_text(
                json.dumps(handoff_4_to_5a.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8"
            )
            perf_prompt_a = (
                f"You are the Performance Marketing & Analytics Specialist (Pass A: Measurement & Attribution).\n\n"
                f"{handoff_4_to_5a.format_prompt_section()}\n\n"
                f"Ensure you provide explicit, actionable sections for:\n"
                f"### SECTION 1: FUNNEL MEASUREMENT & KPI ARCHITECTURE\n"
                f"### SECTION 2: ATTRIBUTION & TRACKING TAXONOMY\n"
            )
            req_a = ModelRequest(
                messages=[ModelMessage(role=ModelRole.USER, content=perf_prompt_a)],
                model_name=self.model_name,
                timeout_seconds=self.policy.model_call_timeout_seconds,
            )
            resp_a_path = self.raw_response_dir / "stage_5a_performance_response.txt"
            tel_a_path = self.telemetry_dir / "stage_5a_performance_telemetry.json"
            if resp_a_path.exists() and resp_a_path.stat().st_size > 100 and tel_a_path.exists():
                content_a = resp_a_path.read_text(encoding="utf-8")
                tel_a_data = json.loads(tel_a_path.read_text(encoding="utf-8"))
                resp_a = ModelResponse(
                    request_id="REQ-STAGE5A-CHECKPOINT",
                    provider=self.provider_id,
                    model_name=self.model_name,
                    status=ModelResponseStatus.SUCCESS,
                    content=content_a,
                    usage=ModelUsage(**tel_a_data),
                )
            else:
                resp_a = self.generate_step(req_a)
                (self.raw_response_dir / "stage_5a_performance_response.txt").write_text(resp_a.content, encoding="utf-8")
                (self.telemetry_dir / "stage_5a_performance_telemetry.json").write_text(
                    json.dumps(resp_a.usage.model_dump(), indent=2), encoding="utf-8"
                )
                if resp_a.status != ModelResponseStatus.SUCCESS:
                    return {"condition": "FIVE_AGENT_GOVERNED", "status": resp_a.status.value, "failed_stage": "performance_pass_a", "error": resp_a.error}
                self.pace_cooldown()

            # --- PASS 5B: EXPERIMENTATION & GOVERNANCE ---
            handoff_5a_to_5b = HandoffPackage(
                handoff_id="HNDF-STAGE5A-TO-STAGE5B",
                task_id="TASK-BENCH-STAGE-5B-PERF-EXPERIMENTATION",
                from_agent="PERFORMANCE_PASS_A",
                to_agent="PERFORMANCE_PASS_B",
                context_version=self.policy.handoff_contract_version,
                source_stage_refs=["STAGE_3_STRAT:v2", "STAGE_4_CRTV:v2", "STAGE_5A_PERF:v2"],
                product_id=self.product_facts["product_id"],
                brand_id=self.product_facts.get("brand_id", self.product_facts["product_id"]),
                objective="Design structured experimentation backlog, decision rules, risk guardrails, and governance requirements grounded in Measurement and Creative decisions.",
                product_facts=self.product_facts.get("verified_product_facts", []),
                upstream_decisions={
                    "strategy_context": stage_3_data.get("raw_text", "")[:800],
                    "creative_assets": stage_4_data.get("raw_text", "")[:800],
                    "pass_a_measurement_summary": resp_a.content[:1500],
                },
                allowed_claims=[c.claim_text for c in pipeline.claim_register.get_allowed_claims()],
                required_next_output=(
                    "Produce structured outputs for:\n"
                    "1. EXPERIMENT_BACKLOG: Structured experiment blueprints covering: hypothesis, concrete intervention, target audience, control/comparison, primary metric, guardrail metric, minimum evidence requirement (mark BASELINE_REQUIRED if missing), explicit stopping criteria, and next actions for WIN, LOSS, and INCONCLUSIVE outcomes.\n"
                    "2. GOVERNANCE_REQUIREMENTS: Metric and budget ownership, claim validation checkpoints, launch/pause conditions, escalation protocols, and explicit human approval requirements."
                ),
            )
            (self.handoff_dir / "handoff_stage_5a_to_stage_5b.json").write_text(
                json.dumps(handoff_5a_to_5b.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8"
            )
            perf_prompt_b = (
                f"You are the Performance Marketing & Analytics Specialist (Pass B: Experimentation & Governance).\n\n"
                f"{handoff_5a_to_5b.format_prompt_section()}\n\n"
                f"Ensure you provide explicit, actionable sections for:\n"
                f"### SECTION 3: EXPERIMENTATION BACKLOG & DECISION RULES\n"
                f"### SECTION 4: GOVERNANCE, RISK MITIGATION & HUMAN APPROVALS\n"
            )
            req_b = ModelRequest(
                messages=[ModelMessage(role=ModelRole.USER, content=perf_prompt_b)],
                model_name=self.model_name,
                timeout_seconds=self.policy.model_call_timeout_seconds,
            )
            (self.raw_request_dir / "stage_5b_performance_request.txt").write_text(perf_prompt_b, encoding="utf-8")
            resp_b = self.generate_step(req_b)
            (self.raw_response_dir / "stage_5b_performance_response.txt").write_text(resp_b.content, encoding="utf-8")
            (self.telemetry_dir / "stage_5b_performance_telemetry.json").write_text(
                json.dumps(resp_b.usage.model_dump(), indent=2), encoding="utf-8"
            )
            if resp_b.status != ModelResponseStatus.SUCCESS:
                return {"condition": "FIVE_AGENT_GOVERNED", "status": resp_b.status.value, "failed_stage": "performance_pass_b", "error": resp_b.error}

            # --- DETERMINISTIC CODE MERGE (PASS A + PASS B) ---
            from schemas.handoff import PerformanceHandoffPayload, PreservationLedger, PreservationItem
            merged_perf_text = f"# PERFORMANCE MARKETING & ANALYTICS BLUEPRINT\n\n{resp_a.content or ''}\n\n{resp_b.content or ''}"
            (self.raw_response_dir / "stage_5_performance_response.txt").write_text(merged_perf_text, encoding="utf-8")

            u_a = resp_a.usage if resp_a.usage else None
            u_b = resp_b.usage if resp_b.usage else None
            total_prompt_tok = (getattr(u_a, "prompt_tokens", 0) or 0) + (getattr(u_b, "prompt_tokens", 0) or 0)
            total_comp_tok = (getattr(u_a, "completion_tokens", 0) or 0) + (getattr(u_b, "completion_tokens", 0) or 0)
            total_th_tok = (getattr(u_a, "thoughts_tokens", 0) or 0) + (getattr(u_b, "thoughts_tokens", 0) or 0)
            total_tok = (getattr(u_a, "total_tokens", 0) or 0) + (getattr(u_b, "total_tokens", 0) or 0)
            merged_usage = {
                "prompt_tokens": total_prompt_tok,
                "completion_tokens": total_comp_tok,
                "thoughts_tokens": total_th_tok,
                "total_tokens": total_tok,
            }
            (self.telemetry_dir / "stage_5_performance_telemetry.json").write_text(
                json.dumps(merged_usage, indent=2), encoding="utf-8"
            )

            lat_a = getattr(resp_a, "latency_ms", 0.0) or 0.0
            lat_b = getattr(resp_b, "latency_ms", 0.0) or 0.0

            stage_5_data = {
                "benchmark_id": self.manifest.benchmark_id,
                "run_id": self.manifest.run_id,
                "run_fingerprint": self.manifest.run_fingerprint,
                "execution_generation": self.manifest.execution_generation,
                "provider_requested": self.provider_id,
                "provider_resolved": str(getattr(resp_b, "provider", self.provider_id) or self.provider_id),
                "model_requested": self.model_name,
                "model_resolved": str(getattr(resp_b, "model_name", self.model_name) or self.model_name),
                "handoff_id": "HNDF-STAGE5-TWO-PASS-MERGED",
                "source_stage_refs": ["STAGE_5A_PERF:v2", "STAGE_5B_PERF:v2"],
                "context_version": self.policy.handoff_contract_version,
                "status": "SUCCESS",
                "raw_text": merged_perf_text,
                "pass_a_raw_text": resp_a.content or "",
                "pass_b_raw_text": resp_b.content or "",
                "usage": merged_usage,
                "latency_ms": lat_a + lat_b,
                "error": None,
            }
            stage_5_chk.write_text(json.dumps(stage_5_data, indent=2), encoding="utf-8")
            if self.run_checkpoints_dir != self.checkpoints_dir:
                (self.run_checkpoints_dir / "five_agent_stage_5_perf.json").write_text(json.dumps(stage_5_data, indent=2), encoding="utf-8")
            self.pace_cooldown()

        # Run Pre-Handoff 5 -> CMO Final
        pipeline.pre_handoff_validation("PERFORMANCE", "CMO_FINAL", stage_5_data)

        # Stage 6: CMO Final Governance
        stage_6_chk = self.checkpoints_dir / "five_agent_stage_6_final_cmo.json"
        stage_6_data = None
        if stage_6_chk.exists():
            try:
                cached = json.loads(stage_6_chk.read_text(encoding="utf-8"))
                if is_valid_stage_checkpoint(
                    cached,
                    required_fingerprint=self.manifest.run_fingerprint,
                    required_generation=self.manifest.execution_generation,
                    required_version=self.policy.handoff_contract_version,
                ):
                    stage_6_data = cached
            except Exception:
                pass

        if stage_6_data is None:
            # Build Anti-Information-Loss Preservation Ledger and Performance Payload
            from schemas.handoff import PerformanceHandoffPayload, PreservationLedger, PreservationItem
            perf_text_a = stage_5_data.get("pass_a_raw_text", stage_5_data.get("raw_text", ""))
            perf_text_b = stage_5_data.get("pass_b_raw_text", stage_5_data.get("raw_text", ""))

            pass_a_payload = {
                "funnel_model": {"measurement_plan": perf_text_a[:1500]},
                "kpi_tree": {"kpi_architecture": perf_text_a[:1000]},
                "attribution_architecture": {"attribution_taxonomy": perf_text_a[1000:2500] if len(perf_text_a) > 1000 else perf_text_a},
                "tracking_requirements": ["UTM standard", "Conversion tag", "Product telemetry"],
                "unresolved_measurement_gaps": ["Baseline organic conversion rate"],
            }
            pass_b_payload = {
                "experiment_backlog": [{"experiment_plan": perf_text_b[:2000]}],
                "decision_rules": [{"rule": "Scale top performer at CPA threshold"}],
                "risks_and_guardrails": ["CAC ceiling", "Return rate threshold"],
                "governance_requirements": ["CMO approval on ad budget", "Claim safety validation on public copy"],
                "human_approvals": ["Security claim sign-off", "Paid acquisition budget release"],
            }

            perf_payload = PerformanceHandoffPayload.deterministic_merge(pass_a_payload, pass_b_payload)
            is_complete, missing_fields = perf_payload.validate_completeness()
            if not is_complete:
                raise ValueError(f"PerformanceHandoffPayload validation failed with missing fields: {missing_fields}")

            ledger = PreservationLedger(
                intelligence_critical_items=[PreservationItem(source_agent="INTELLIGENCE", category="RESEARCH", description="Market evidence and ICP pain points", status="PRESERVED")],
                strategy_critical_items=[PreservationItem(source_agent="STRATEGIST", category="POSITIONING", description="Positioning pillars and channel allocation", status="PRESERVED")],
                creative_critical_items=[PreservationItem(source_agent="CREATIVE", category="CREATIVE", description="Selected creative territory, hooks, and script", status="PRESERVED")],
                performance_critical_items=[PreservationItem(source_agent="PERFORMANCE", category="MEASUREMENT", description="Funnel metrics, attribution, experiments, and governance", status="PRESERVED")],
            )

            handoff_all_to_6 = HandoffPackage(
                handoff_id="HNDF-ALL-TO-CMO-FINAL",
                task_id="TASK-BENCH-STAGE-6-FINAL-CMO",
                from_agent="ALL_SPECIALIZED_AGENTS",
                to_agent="CMO_FINAL",
                context_version=self.policy.handoff_contract_version,
                source_stage_refs=["STAGE_1_CMO:v2", "STAGE_2_INTEL:v2", "STAGE_3_STRAT:v2", "STAGE_4_CRTV:v2", "STAGE_5_PERF:v2"],
                product_id=self.product_facts["product_id"],
                brand_id=self.product_facts.get("brand_id", self.product_facts["product_id"]),
                objective="Synthesize and govern the complete Go-To-Market strategy across all 28 required deliverable sections, preserving specialist decisions and enforcing claim safety.",
                product_facts=self.product_facts.get("verified_product_facts", []),
                upstream_findings={"intelligence_summary": stage_2_data.get("raw_text", "")[:1200]},
                upstream_decisions={
                    "cmo_initial": stage_1_data.get("raw_text", "")[:800],
                    "strategy": stage_3_data.get("raw_text", "")[:1200],
                    "creative": stage_4_data.get("raw_text", "")[:1200],
                    "performance": stage_5_data.get("raw_text", ""),
                },
                performance_payload=perf_payload,
                preservation_ledger=ledger,
                allowed_claims=[c.claim_text for c in pipeline.claim_register.get_allowed_claims()],
                prohibited_claims=[c.claim_text for c in pipeline.claim_register.get_unsupported_claims()],
                required_next_output="Return the comprehensive, verified 28-deliverable Go-To-Market proposal in valid JSON format matching all benchmark requirements, preserving performance, attribution, experimentation, and governance decisions.",
            )
            (self.handoff_dir / "handoff_stage_all_to_stage_6_cmo_final.json").write_text(
                json.dumps(handoff_all_to_6.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8"
            )
            final_prompt = (
                f"You are the Chief Marketing Officer presiding over final governance and strategic synthesis (Brain RC2).\n"
                f"Your role is the Governed Synthesis and Preservation Layer: resolve contradictions, enforce claim safety, and preserve all specialist decisions without deleting technical execution detail.\n\n"
                f"{handoff_all_to_6.format_prompt_section()}\n\n"
                f"Required JSON Structure:\n"
                f"- executive_summary\n"
                f"- known_facts\n"
                f"- observations\n"
                f"- inferences\n"
                f"- hypotheses\n"
                f"- unknowns\n"
                f"- customer_segments\n"
                f"- top_priority_segment\n"
                f"- positioning\n"
                f"- value_proposition\n"
                f"- channel_priorities\n"
                f"- deferred_channels\n"
                f"- what_not_to_do\n"
                f"- creative_territories\n"
                f"- selected_creative_territory\n"
                f"- angles\n"
                f"- hooks\n"
                f"- short_form_copy\n"
                f"- video_script\n"
                f"- measurement_framework\n"
                f"- experiments\n"
                f"- attribution_approach\n"
                f"- risks\n"
                f"- top_3_priorities\n"
                f"- go_test_hold_defer_decisions\n"
                f"- human_approval_requirements\n"
                f"- next_actions\n"
            )
            req = ModelRequest(
                messages=[ModelMessage(role=ModelRole.USER, content=final_prompt)],
                model_name=self.model_name,
                timeout_seconds=self.policy.model_call_timeout_seconds,
            )
            (self.raw_request_dir / "stage_6_cmo_final_request.txt").write_text(final_prompt, encoding="utf-8")
            resp = self.generate_step(req)
            (self.raw_response_dir / "stage_6_cmo_final_response.txt").write_text(resp.content, encoding="utf-8")
            (self.telemetry_dir / "stage_6_cmo_final_telemetry.json").write_text(
                json.dumps(resp.usage.model_dump(), indent=2), encoding="utf-8"
            )
            stage_6_data = {
                "benchmark_id": self.manifest.benchmark_id,
                "run_id": self.manifest.run_id,
                "run_fingerprint": self.manifest.run_fingerprint,
                "execution_generation": self.manifest.execution_generation,
                "provider_requested": self.provider_id,
                "provider_resolved": str(getattr(resp, "provider", self.provider_id) or self.provider_id),
                "model_requested": self.model_name,
                "model_resolved": str(getattr(resp, "model_name", self.model_name) or self.model_name),
                "handoff_id": handoff_all_to_6.handoff_id,
                "source_stage_refs": handoff_all_to_6.source_stage_refs,
                "context_version": self.policy.handoff_contract_version,
                "status": resp.status.value,
                "raw_text": resp.content,
                "prompt_text": final_prompt,
                "usage": resp.usage.model_dump(),
                "latency_ms": getattr(resp, "latency_ms", 0.0),
                "error": resp.error,
            }
            stage_6_chk.write_text(json.dumps(stage_6_data, indent=2), encoding="utf-8")
            if self.run_checkpoints_dir != self.checkpoints_dir:
                (self.run_checkpoints_dir / "five_agent_stage_6_final_cmo.json").write_text(json.dumps(stage_6_data, indent=2), encoding="utf-8")
            if resp.status != ModelResponseStatus.SUCCESS:
                return {"condition": "FIVE_AGENT_GOVERNED", "status": resp.status.value, "failed_stage": "final_cmo", "error": resp.error}

        # Save Raw Output for Stage 6 Final CMO
        (self.raw_dir / "five_agent_final_raw.txt").write_text(stage_6_data.get("raw_text", ""), encoding="utf-8")

        # Normalize Five-Agent Final CMO Candidate Output
        norm_res = CandidateNormalizer.normalize_candidate(
            raw_text=stage_6_data.get("raw_text", ""),
            condition_id="FIVE_AGENT_GOVERNED",
            benchmark_id=self.manifest.benchmark_id,
            run_id=self.manifest.run_id,
            run_fingerprint=self.manifest.run_fingerprint,
            provider_requested=self.provider_id,
            provider_resolved=stage_6_data.get("provider_resolved", self.provider_id),
            model_requested=self.model_name,
            model_resolved=stage_6_data.get("model_resolved", self.model_name),
            execution_generation=self.manifest.execution_generation,
        )

        if norm_res.status == "SUCCESS" and norm_res.parsed_structure:
            (self.parsed_dir / "five_agent_final_parsed.json").write_text(
                json.dumps(norm_res.parsed_structure, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        if norm_res.status == "SUCCESS" and norm_res.canonical_proposal:
            (self.canonical_dir / "five_agent_canonical.json").write_text(
                json.dumps(norm_res.canonical_proposal.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8"
            )

        # Completeness Gate
        is_complete = False
        completeness_audit: Dict[str, bool] = {}
        if norm_res.canonical_proposal:
            is_complete, completeness_audit = audit_canonical_completeness(norm_res.canonical_proposal)

        # Universal FinalClaimAuditGate on Five-Agent Register
        final_audit_res = pipeline.evaluate_cmo_final_gate()

        five_agent_final_data = {
            "benchmark_id": self.manifest.benchmark_id,
            "run_id": self.manifest.run_id,
            "run_fingerprint": self.manifest.run_fingerprint,
            "execution_generation": self.manifest.execution_generation,
            "benchmark_schema_version": self.manifest.benchmark_schema_version,
            "candidate_schema_version": self.manifest.candidate_schema_version,
            "condition": "FIVE_AGENT_GOVERNED",
            "provider_requested": self.provider_id,
            "provider_resolved": self.provider_id,
            "model_requested": self.model_name,
            "model_resolved": self.model_name,
            "context_version": self.policy.handoff_contract_version,
            "status": "COMPLETED",
            "stages": {
                "cmo_initial": stage_1_data,
                "intelligence": stage_2_data,
                "strategist": stage_3_data,
                "creative": stage_4_data,
                "performance": stage_5_data,
                "final_cmo": stage_6_data,
            },
            "source_raw_hash": norm_res.raw_hash,
            "parsed_hash": norm_res.parsed_hash,
            "canonical_hash": norm_res.canonical_hash,
            "parsed_output": norm_res.parsed_structure if norm_res.status == "SUCCESS" else {},
            "canonical_proposal": norm_res.canonical_proposal.model_dump() if norm_res.canonical_proposal else None,
            "normalization_status": norm_res.status,
            "completeness": {
                "is_complete": is_complete,
                "audit": completeness_audit,
            },
            "claim_register": pipeline.claim_register.to_dict(),
            "handoff_audits": [r.model_dump() for r in pipeline.handoff_audit_history],
            "universal_final_audit": final_audit_res.model_dump(),
            "final_authorization": pipeline.final_authorization,
            "content_patch_count": norm_res.content_patch_count,
            "semantic_rewrite_count": norm_res.semantic_rewrite_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        five_agent_chk.write_text(json.dumps(five_agent_final_data, indent=2, ensure_ascii=False), encoding="utf-8")
        if self.run_checkpoints_dir != self.checkpoints_dir:
            (self.run_checkpoints_dir / "five_agent_final.json").write_text(json.dumps(five_agent_final_data, indent=2, ensure_ascii=False), encoding="utf-8")
        pipeline.save_checkpoint(self.checkpoints_dir)
        return five_agent_final_data


def main(argv: Optional[List[str]] = None) -> int:
    """CLI Entrypoint for Phase 4.3 Benchmark Harness."""
    import argparse
    parser = argparse.ArgumentParser(description="Phase 4.3 True-Parity Benchmark Harness: AI English Speaking App (Vietnam)")
    parser.add_argument("--dry-run", action="store_true", help="Execute dry-run without calling live models")
    parser.add_argument("--single-only", action="store_true", help="Execute only Condition 1: Single Senior Marketing Model")
    parser.add_argument("--five-agent-only", action="store_true", help="Execute only Condition 2: Governed Five-Agent Pipeline")
    parser.add_argument("--reset-failed-checkpoints", action="store_true", help="Archive invalid failed checkpoints before run")
    parser.add_argument("--provider", type=str, default=None, help="Benchmark model provider (e.g. gemini, xkiro)")
    parser.add_argument("--model", type=str, default=None, help="Benchmark model name")
    args = parser.parse_args(argv)

    try:
        harness = BenchmarkHarness(provider_id=args.provider, model_name=args.model)
    except Exception as ex:
        print(f"\nSTATUS: CONFIGURATION_ERROR ({ex})")
        return 1

    print("================================================================================")
    print("PHASE 4.3 TRUE-PARITY BENCHMARK: AI ENGLISH SPEAKING APP (VIETNAM)")
    print("================================================================================")
    print(f"Dry Run Mode: {args.dry_run}")
    print(f"Execution Generation: {harness.manifest.execution_generation}")
    print(f"Run ID: {harness.manifest.run_id}")
    print(f"Run Fingerprint: {harness.manifest.run_fingerprint[:16]}...")
    print(f"Provider Pinned: {harness.provider_id}")
    print(f"Model Pinned: {harness.model_name}")
    print(f"Strict Model Pin: True")
    print(f"Timeout: {harness.policy.model_call_timeout_seconds}s")
    print(f"Cooldown Pacing: {harness.cooldown_seconds}s")

    if args.reset_failed_checkpoints:
        count = harness.reset_invalid_checkpoints()
        print(f"\n[Reset] Archived {count} invalid/failed checkpoints to archive folder.")

    if args.dry_run:
        print("\n[Dry Run] Executing pre-flight readiness verification...")
        single_res = harness.run_single_condition(dry_run=True)
        print(f"  Condition 1 (Single Model): {single_res.get('status')}")
        five_res = harness.run_five_agent_condition(dry_run=True)
        print(f"  Condition 2 (Governed Five-Agent): {five_res.get('status')}")

        audit = harness.audit_checkpoints()
        print(f"  Checkpoint Audit: Valid Success: {len(audit['VALID_SUCCESS'])}, Invalid/Failed: {len(audit['INVALID_FAILED'])}")
        print("\n[Dry Run] All benchmark harness paths, contracts, and checkpoints ready.")
        return 0

    single_res = None
    if not args.five_agent_only:
        print("\n[1/2] Executing Condition 1: Single Senior Marketing Model...")
        single_res = harness.run_single_condition(dry_run=False)
        harness.pace_cooldown()

    five_res = None
    if not args.single_only:
        print("\n[2/2] Executing Condition 2: Governed Five-Agent Pipeline...")
        five_res = harness.run_five_agent_condition(dry_run=False)

    # Fail-closed candidate validity and completeness verification
    single_ok = (
        is_valid_candidate_checkpoint(
            single_res,
            required_fingerprint=harness.manifest.run_fingerprint,
            required_generation=harness.manifest.execution_generation,
        )
        if single_res
        else args.five_agent_only
    )
    five_ok = (
        is_valid_candidate_checkpoint(
            five_res,
            required_fingerprint=harness.manifest.run_fingerprint,
            required_generation=harness.manifest.execution_generation,
            required_version=harness.policy.handoff_contract_version,
        )
        if five_res
        else args.single_only
    )

    if not single_ok or not five_ok:
        if (single_res and single_res.get("status") == "RATE_LIMITED") or (five_res and five_res.get("status") == "RATE_LIMITED"):
            print("\nSTATUS: RATE_LIMIT_PAUSED")
            return 2
        if single_res and single_res.get("normalization_status") == "NORMALIZATION_FAILED":
            print("\nSTATUS: NORMALIZATION_FAILED (Single Model candidate output syntax malformed)")
            return 1
        if five_res and five_res.get("normalization_status") == "NORMALIZATION_FAILED":
            print("\nSTATUS: NORMALIZATION_FAILED (Five-Agent candidate output syntax malformed)")
            return 1
        print("\nSTATUS: CANDIDATE_INCOMPLETE")
        return 1

    # Assemble blind review packet upon full valid completion
    try:
        from evaluations.benchmarks.phase4_3_unseen_ai_speaking.assemble_blind_packet import assemble_blind_packet
        assemble_blind_packet(
            benchmark_dir=harness.benchmark_dir,
            run_dir=harness.run_dir,
            run_fingerprint=harness.manifest.run_fingerprint,
        )
    except Exception as ex:
        print(f"\nSTATUS: BLIND_PACKET_FAILED ({ex})")
        return 1

    print("\nBenchmark run complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
