"""Phase 4.3C.9: Fair Three-Way Benchmark Protocol Specification & Freeze.

Defines the frozen, immutable benchmark protocol for comparing:
Candidate A: Five-Agent V2 (Governed Multi-Agent)
Candidate B: Single-Agent Multi-Pass (Resource-Matched Memory Control)
Candidate C: Single-Agent One-Shot (Practical Baseline)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

BENCHMARK_DIR = Path(__file__).resolve().parent

# 1. Benchmark Inputs
FACTS_PATH = BENCHMARK_DIR / "product_facts.json"
EVIDENCE_PATH = BENCHMARK_DIR / "evidence_bundle.json"
OBJECTIVE_PATH = BENCHMARK_DIR / "business_objective.json"

# 2. Canonical 28 Deliverable Keys
CANONICAL_28_DELIVERABLES = [
    "executive_summary",
    "known_facts",
    "observations",
    "inferences",
    "hypotheses",
    "unknowns",
    "customer_segments",
    "top_priority_segment",
    "positioning",
    "value_proposition",
    "channel_priorities",
    "deferred_channels",
    "what_not_to_do",
    "creative_territories",
    "selected_creative_territory",
    "angles",
    "hooks",
    "short_form_copy",
    "video_script",
    "measurement_framework",
    "experiments",
    "attribution_approach",
    "risks",
    "top_3_priorities",
    "go_test_hold_defer_decisions",
    "human_approval_requirements",
    "next_actions",
    "claim_governance",
]

# 3. 14-Dimension Evaluation Rubric
EVALUATION_RUBRIC_SPEC = {
    "dimensions": [
        {"id": "DIM-01", "name": "Research Quality & Qualitative Discovery", "weight": 0.08, "scale": "1-10", "description": "Depth of customer pain points, JTBD understanding, speaking anxiety analysis, competitor landscape."},
        {"id": "DIM-02", "name": "Evidence Discipline & Grounding", "weight": 0.08, "scale": "1-10", "description": "Strict adherence to verified product facts, zero factual fabrication, correct citation of evidence IDs."},
        {"id": "DIM-03", "name": "Customer Segmentation Quality", "weight": 0.07, "scale": "1-10", "description": "Precision of demographic/psychographic tiers, prioritization rationale for top segment."},
        {"id": "DIM-04", "name": "Strategic Positioning Architecture", "weight": 0.08, "scale": "1-10", "description": "Clarity of value proposition, differentiation from human tutors and passive apps."},
        {"id": "DIM-05", "name": "Channel Strategy & Discipline", "weight": 0.07, "scale": "1-10", "description": "Justified primary/secondary/deferred channels, clear rationale for deferred channels."},
        {"id": "DIM-06", "name": "Creative Quality & Emotional Resonance", "weight": 0.08, "scale": "1-10", "description": "Distinct creative territories, cultural relevance to Vietnamese learners, scroll-stopping hooks."},
        {"id": "DIM-07", "name": "Copywriting & Script Executability", "weight": 0.07, "scale": "1-10", "description": "Production readiness of short-form ad copy and video script with visual/audio cues."},
        {"id": "DIM-08", "name": "Performance Funnel & Metric Architecture", "weight": 0.07, "scale": "1-10", "description": "Full-funnel KPI hierarchy (CAC, onboarding completion, D7 retention targets)."},
        {"id": "DIM-09", "name": "Experimentation Rigor & Falsifiability", "weight": 0.08, "scale": "1-10", "description": "Testable hypotheses, clear treatments/controls, statistical stopping rules."},
        {"id": "DIM-10", "name": "Attribution & Technical Tracking", "weight": 0.06, "scale": "1-10", "description": "SKAdNetwork 4.0, MMP postbacks, CAPI, UTM taxonomy."},
        {"id": "DIM-11", "name": "Claim Safety & Regulatory Compliance", "weight": 0.08, "scale": "1-10", "description": "Absolute absence of ungrounded guarantees, IELTS score promises, or unauthorized claims."},
        {"id": "DIM-12", "name": "Strategic Governance & Approvals", "weight": 0.06, "scale": "1-10", "description": "Go/Test/Hold/Defer decisions, explicit human approval gates before spend."},
        {"id": "DIM-13", "name": "Internal Section Consistency & Lineage", "weight": 0.06, "scale": "1-10", "description": "Coherence between research -> strategy -> creative -> performance -> CMO governance."},
        {"id": "DIM-14", "name": "Canonical Deliverable Completeness", "weight": 0.06, "scale": "1-10", "description": "Presence, depth, and substance across all 28 canonical deliverable sections."},
    ],
    "total_weight": 1.00,
    "scoring_scale": {"min": 1.0, "max": 10.0, "step": 0.5},
}

# 4. Dynamic Resource Matching Specification
RESOURCE_MATCH_SPEC = {
    "policy_id": "DYNAMIC_FRESH_A_RESOURCE_MATCHING_V2",
    "resource_match_metric": "PROVIDER_TOTAL_TOKENS",
    "target_formula": "ACTUAL_FRESH_A_PROVIDER_TOTAL_TOKENS",
    "resource_token_tolerance_percent": 10.0,
    "historical_validation_baseline": {
        "run_id": "RUN-PHASE4-3-V2-LIVE-001",
        "provider_total_tokens": 29421,
        "max_output_tokens": 4096,
        "status": "HISTORICAL_VALIDATION_ONLY_NOT_USED_AS_LIVE_B_TARGET",
    },
    "fresh_candidate_a_requirement": {
        "run_id_prefix": "RUN-PHASE4-3-V2-BENCH",
        "max_output_tokens": 8192,
        "fresh_run_mandatory": True,
    },
    "dynamic_target_computation": "B_TARGET = A_ACTUAL_PROVIDER_TOTAL_TOKENS; B_MIN = round(B_TARGET * 0.90); B_MAX = round(B_TARGET * 1.10)",
    "target_candidate_b_passes": 5,
    "candidate_c_model_calls": 1,
    "information_firewall": {
        "A_TO_B_CONTENT_LEAK_COUNT": 0,
        "permitted_runtime_fields_from_a": ["A_ACTUAL_PROVIDER_TOTAL_TOKENS"],
        "prohibited_runtime_fields_from_a": [
            "raw_text",
            "findings",
            "decisions",
            "canonical_proposal",
            "scoring",
            "completeness",
        ],
    },
    "budget_behavior_rules": {
        "natural_within_bounds": "RESOURCE_PARITY = PASS",
        "natural_under_budget": "RESOURCE_PARITY = UNDER_BUDGET (NO filler text generation)",
        "natural_over_budget": "RESOURCE_PARITY = OVER_BUDGET (NO active response truncation)",
    },
    "retry_accounting_rules": {
        "TOTAL_COMPUTE_CONSUMED": "Sum of all provider-reported tokens across all attempts",
        "VALID_CANDIDATE_GENERATION_TOKENS": "Tokens belonging strictly to successful attempts",
    },
}

# 5. Frozen Execution Order Specification
EXECUTION_ORDER_SPEC = {
    "step_1": "Execute Candidate A fresh under common 8192 config (new run ID)",
    "step_2": "Seal Candidate A raw artifacts immediately",
    "step_3": "Read ONLY Candidate A provider_total_tokens for resource matching",
    "step_4": "Compute Candidate B target budget range deterministically (A_TOTAL * [0.90, 1.10])",
    "step_5": "Execute Candidate B using frozen B prompts and 5 passes with scratchpad",
    "step_6": "Execute Candidate C using frozen C prompt and 1 call",
    "step_7": "Seal all candidate artifacts",
    "step_8": "Begin 3-way double blind evaluation",
}

# 6. Model Execution Policy
MODEL_CONFIG_SPEC = {
    "provider_id": "gemini",
    "requested_model": "gemini-flash-latest",
    "resolved_model": "gemini-3.5-flash",
    "provider_protocol": "gemini_native",
    "strict_model_pin": True,
    "timeout_seconds": 180.0,
    "max_tokens_per_call": 8192,
    "temperature": 0.2,
    "cooldown_seconds": 15.0,
}

# 6. Canonical Assembler & Invariant Policy
ASSEMBLER_POLICY_SPEC = {
    "policy_id": "NEUTRAL_CANONICAL_ASSEMBLER_V2",
    "truncation_policy": "PARTIAL_IMMUTABLE_SALVAGE",
    "allowed_actions": [
        "COLLECT_STAGE_DELIVERABLES",
        "STRUCTURAL_JSON_PARSING",
        "SCHEMA_FIELD_MAPPING",
        "VERBATIM_UNCLOSED_FIELD_SALVAGE",
        "VERBATIM_MARKDOWN_SECTION_EXTRACTION",
    ],
    "prohibited_actions": [
        "SYNTHETIC_CONTENT_GENERATION",
        "SEMANTIC_REWRITING",
        "PROMPT_OR_OUTPUT_PATCHING",
        "TRUNCATED_JSON_CLOSURE_FABRICATION",
        "UNSUPPORTED_CLAIM_INJECTION",
    ],
    "invariant_requirements": {
        "CONTENT_PATCH_COUNT": 0,
        "SEMANTIC_REWRITE_COUNT": 0,
        "FABRICATED_DELIVERABLE_COUNT": 0,
        "IDENTITY_LEAK_COUNT": 0,
    },
}

# 7. Failure Policy
FAILURE_POLICY_SPEC = {
    "policy_id": "PARTIAL_IMMUTABLE_SALVAGE_FAIL_CLOSED_V2",
    "truncation_policy": "PARTIAL_IMMUTABLE_SALVAGE",
    "model_call_timeout_seconds": 180.0,
    "max_retries_per_call": 1,
    "retry_conditions": ["HTTP_503_SERVICE_UNAVAILABLE", "SOCKET_TIMEOUT"],
    "non_retryable_conditions": ["HTTP_400_BAD_REQUEST", "HTTP_403_FORBIDDEN", "HTTP_404_NOT_FOUND", "HTTP_429_RATE_LIMIT"],
    "malformed_output_action": "REJECT_UNPARSEABLE_SECTIONS_SALVAGE_VERBATIM_COMPLETED_FIELDS",
    "truncated_output_action": "PARTIAL_IMMUTABLE_SALVAGE_VERBATIM_COMPLETED_ONLY",
    "manual_completion_allowed": False,
    "cross_candidate_fallback_allowed": False,
}

# 8. Blinding Policy
BLINDING_POLICY_SPEC = {
    "policy_id": "DOUBLE_BLIND_EVALUATION_POLICY_V2",
    "anonymous_labels": ["Candidate X", "Candidate Y", "Candidate Z"],
    "redaction_rules": [
        "STRIP_AGENT_NAMES",
        "STRIP_ARCHITECTURE_METADATA",
        "STRIP_TOKEN_AND_USAGE_TELEMETRY",
        "STRIP_RUN_IDS_AND_FILE_PATHS",
        "STRIP_HANDOFF_IDENTIFIERS",
        "STRIP_SPECIALIST_LABELS",
    ],
    "required_blind_leak_count": 0,
}


def compute_hash(data: Any) -> str:
    """Compute deterministic SHA-256 hash of a JSON-serializable object or string."""
    if isinstance(data, (bytes, bytearray)):
        return hashlib.sha256(data).hexdigest()
    if isinstance(data, str):
        return hashlib.sha256(data.encode("utf-8")).hexdigest()
    normalized = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass
class BenchmarkProtocolManifest:
    """Machine-readable protocol manifest with cryptographic freeze hashes."""
    protocol_id: str
    version: str
    created_at: str

    benchmark_input_hash: str
    deliverable_schema_hash: str
    evaluation_rubric_hash: str
    resource_match_hash: str
    execution_order_hash: str
    model_config_hash: str
    assembler_policy_hash: str
    failure_policy_hash: str
    blinding_policy_hash: str

    prompt_hash_a: str = ""
    prompt_hash_b: str = ""
    prompt_hash_c: str = ""

    candidate_a_spec: Dict[str, Any] = field(default_factory=dict)
    candidate_b_spec: Dict[str, Any] = field(default_factory=dict)
    candidate_c_spec: Dict[str, Any] = field(default_factory=dict)

    evaluation_rubric: Dict[str, Any] = field(default_factory=dict)
    resource_match: Dict[str, Any] = field(default_factory=dict)
    execution_order: Dict[str, Any] = field(default_factory=dict)
    model_config: Dict[str, Any] = field(default_factory=dict)
    assembler_policy: Dict[str, Any] = field(default_factory=dict)
    failure_policy: Dict[str, Any] = field(default_factory=dict)
    blinding_policy: Dict[str, Any] = field(default_factory=dict)

    previous_protocol_fingerprint: str = "00d17aaab9ed79a471a7d7826d40013806eb59786b2124066c249bb4ba52387f"
    previous_fingerprint_status: str = "SUPERSEDED_BEFORE_LIVE_EXECUTION"
    protocol_fingerprint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def create(cls) -> BenchmarkProtocolManifest:
        # Load source benchmark files
        facts_bytes = FACTS_PATH.read_bytes()
        evidence_bytes = EVIDENCE_PATH.read_bytes()
        obj_bytes = OBJECTIVE_PATH.read_bytes()
        combined_input = facts_bytes + b"||" + evidence_bytes + b"||" + obj_bytes

        facts_json = json.loads(facts_bytes.decode("utf-8"))
        evidence_json = json.loads(evidence_bytes.decode("utf-8"))
        obj_json = json.loads(obj_bytes.decode("utf-8"))

        from evaluations.benchmarks.phase4_3_unseen_ai_speaking.prompt_generators import (
            build_candidate_a_stage_1_prompt,
            build_candidate_b_pass_1_prompt,
            build_candidate_b_pass_2_prompt,
            build_candidate_b_pass_3_prompt,
            build_candidate_b_pass_4_prompt,
            build_candidate_b_pass_5_prompt,
            build_candidate_c_one_shot_prompt,
        )

        # Compute prompt hashes
        p_a1 = build_candidate_a_stage_1_prompt(facts_json, evidence_json)
        prompt_hash_a = compute_hash(p_a1)

        p_b1 = build_candidate_b_pass_1_prompt(facts_json, evidence_json, obj_json)
        p_b2 = build_candidate_b_pass_2_prompt(facts_json, "[SCRATCHPAD_MEMORY_V2]")
        p_b3 = build_candidate_b_pass_3_prompt(facts_json, "[SCRATCHPAD_MEMORY_V2]")
        p_b4 = build_candidate_b_pass_4_prompt(facts_json, "[SCRATCHPAD_MEMORY_V2]")
        p_b5 = build_candidate_b_pass_5_prompt(facts_json, "[SCRATCHPAD_MEMORY_V2]")
        prompt_hash_b = compute_hash(f"{p_b1}||{p_b2}||{p_b3}||{p_b4}||{p_b5}")

        p_c = build_candidate_c_one_shot_prompt(facts_json, evidence_json, obj_json)
        prompt_hash_c = compute_hash(p_c)

        bench_input_hash = compute_hash(combined_input)
        schema_hash = compute_hash(CANONICAL_28_DELIVERABLES)
        rubric_hash = compute_hash(EVALUATION_RUBRIC_SPEC)
        resource_hash = compute_hash(RESOURCE_MATCH_SPEC)
        exec_order_hash = compute_hash(EXECUTION_ORDER_SPEC)
        model_hash = compute_hash(MODEL_CONFIG_SPEC)
        assembler_hash = compute_hash(ASSEMBLER_POLICY_SPEC)
        failure_hash = compute_hash(FAILURE_POLICY_SPEC)
        blinding_hash = compute_hash(BLINDING_POLICY_SPEC)

        candidate_a_spec = {
            "candidate_id": "CANDIDATE_A",
            "name": "Five-Agent Governed Multi-Agent V2",
            "architecture": "ROLE_SPECIALIZED_MULTI_AGENT",
            "stages": 6,
            "stage_flow": ["cmo_initial", "intelligence", "strategist", "creative", "performance", "final_cmo"],
            "handoff_contract": "HandoffPackage_v2",
            "prompt_hash": prompt_hash_a,
            "fresh_run_mandatory": True,
            "max_output_tokens": 8192,
            "historical_baseline_run_id": "RUN-PHASE4-3-V2-LIVE-001 (HISTORICAL_4096_CEILING_ONLY)",
        }

        candidate_b_spec = {
            "candidate_id": "CANDIDATE_B",
            "name": "Single-Agent Multi-Pass (Resource-Matched Control)",
            "architecture": "SINGLE_AGENT_ITERATIVE_SCRATCHPAD",
            "identity": "UNIFIED_SINGLE_PLANNING_ENGINE",
            "passes": 5,
            "pass_flow": [
                "pass_1_research_and_context",
                "pass_2_positioning_and_channels",
                "pass_3_creative_and_hooks",
                "pass_4_performance_and_experiments",
                "pass_5_governance_and_synthesis",
            ],
            "state_mechanism": "STRUCTURED_WORKING_MEMORY_SCRATCHPAD",
            "prompt_hash": prompt_hash_b,
            "pass_prompt_hashes": {
                "pass_1": compute_hash(p_b1),
                "pass_2": compute_hash(p_b2),
                "pass_3": compute_hash(p_b3),
                "pass_4": compute_hash(p_b4),
                "pass_5": compute_hash(p_b5),
            },
            "resource_target_formula": "ACTUAL_FRESH_A_PROVIDER_TOTAL_TOKENS",
            "token_budget_tolerance_percent": 10.0,
            "historical_a_reference_tokens": 29421,
            "historical_a_used_as_live_b_target": False,
            "max_output_tokens": 8192,
        }

        candidate_c_spec = {
            "candidate_id": "CANDIDATE_C",
            "name": "Single-Agent One-Shot (Practical Baseline)",
            "architecture": "SINGLE_AGENT_ONE_SHOT",
            "identity": "UNIFIED_SINGLE_PLANNING_ENGINE",
            "passes": 1,
            "prompt_style": "DIRECT_ALL_IN_ONE_PROPOSAL_REQUEST",
            "prompt_hash": prompt_hash_c,
            "target_deliverables": 28,
            "max_output_tokens": 8192,
        }

        raw_fingerprint_data = (
            f"{bench_input_hash}:"
            f"{schema_hash}:"
            f"{rubric_hash}:"
            f"{resource_hash}:"
            f"{exec_order_hash}:"
            f"{model_hash}:"
            f"{assembler_hash}:"
            f"{failure_hash}:"
            f"{blinding_hash}:"
            f"{prompt_hash_a}:"
            f"{prompt_hash_b}:"
            f"{prompt_hash_c}"
        )
        protocol_fingerprint = compute_hash(raw_fingerprint_data)

        return cls(
            protocol_id="PHASE4_3C_9_FAIR_THREE_WAY_BENCHMARK",
            version="1.1.0",
            created_at=datetime.now(timezone.utc).isoformat(),
            benchmark_input_hash=bench_input_hash,
            deliverable_schema_hash=schema_hash,
            evaluation_rubric_hash=rubric_hash,
            resource_match_hash=resource_hash,
            execution_order_hash=exec_order_hash,
            model_config_hash=model_hash,
            assembler_policy_hash=assembler_hash,
            failure_policy_hash=failure_hash,
            blinding_policy_hash=blinding_hash,
            prompt_hash_a=prompt_hash_a,
            prompt_hash_b=prompt_hash_b,
            prompt_hash_c=prompt_hash_c,
            candidate_a_spec=candidate_a_spec,
            candidate_b_spec=candidate_b_spec,
            candidate_c_spec=candidate_c_spec,
            evaluation_rubric=EVALUATION_RUBRIC_SPEC,
            resource_match=RESOURCE_MATCH_SPEC,
            execution_order=EXECUTION_ORDER_SPEC,
            model_config=MODEL_CONFIG_SPEC,
            assembler_policy=ASSEMBLER_POLICY_SPEC,
            failure_policy=FAILURE_POLICY_SPEC,
            blinding_policy=BLINDING_POLICY_SPEC,
            previous_protocol_fingerprint="00d17aaab9ed79a471a7d7826d40013806eb59786b2124066c249bb4ba52387f",
            previous_fingerprint_status="SUPERSEDED_BEFORE_LIVE_EXECUTION",
            protocol_fingerprint=protocol_fingerprint,
        )


def export_protocol_manifest(output_path: Optional[Path] = None) -> Path:
    """Generate and write the frozen benchmark protocol manifest JSON."""
    manifest = BenchmarkProtocolManifest.create()
    target = output_path or (BENCHMARK_DIR / "phase4_3c_9_benchmark_protocol.json")
    target.write_text(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return target


if __name__ == "__main__":
    out_file = export_protocol_manifest()
    print(f"Exported Benchmark Protocol Manifest to {out_file}")
    manifest = BenchmarkProtocolManifest.create()
    print(f"BENCHMARK_PROTOCOL_FINGERPRINT = {manifest.protocol_fingerprint}")
    print(f"BENCHMARK_INPUT_HASH = {manifest.benchmark_input_hash}")
    print(f"DELIVERABLE_SCHEMA_HASH = {manifest.deliverable_schema_hash}")
    print(f"EVALUATION_RUBRIC_HASH = {manifest.evaluation_rubric_hash}")
