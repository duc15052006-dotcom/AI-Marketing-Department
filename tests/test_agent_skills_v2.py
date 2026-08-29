from runtime.agent_skills import (
    PERMANENT_AGENT_IDS,
    SKILL_CONTRACTS,
    get_agent_skill_contract,
    render_agent_skill_context,
)


def test_exactly_five_permanent_agent_skill_contracts():
    assert PERMANENT_AGENT_IDS == (
        "cmo",
        "intelligence",
        "strategist",
        "creative",
        "performance",
    )
    assert tuple(SKILL_CONTRACTS.keys()) == PERMANENT_AGENT_IDS
    assert "final_cmo" not in SKILL_CONTRACTS


def test_all_skill_contracts_include_truth_and_governance_prohibitions():
    for agent_id in PERMANENT_AGENT_IDS:
        contract = get_agent_skill_contract(agent_id)
        joined = " ".join(contract.prohibited).lower()
        assert "fabricate" in joined
        assert "toolgateway" in joined
        assert "credentials" in joined


def test_intelligence_contract_requires_iterative_research_truth():
    contract = get_agent_skill_contract("intelligence")
    skills = " ".join(contract.skills).lower()
    prohibited = " ".join(contract.prohibited).lower()
    stopping = " ".join(contract.stopping_rules).lower()
    assert "multi-query" in skills
    assert "source reading" in skills
    assert "evidence-gap" in skills
    assert "literal-search vague follow-ups" in prohibited
    assert "critical evidence gap" in stopping


def test_performance_contract_forbids_fake_metrics_and_hardcoded_targets():
    contract = get_agent_skill_contract("performance")
    prohibited = " ".join(contract.prohibited).lower()
    assert "hard-code business kpi targets" in prohibited
    assert "fabricate attribution shares" in prohibited
    assert "planning assumptions separate from measured results" in prohibited


def test_render_is_bounded_and_rejects_unknown_agent():
    rendered = render_agent_skill_context("cmo", max_chars=500)
    assert len(rendered) <= 500
    assert "CMO" in rendered

    try:
        get_agent_skill_contract("agent6")
    except KeyError as exc:
        assert "UNKNOWN_PERMANENT_AGENT" in str(exc)
    else:
        raise AssertionError("unknown/Agent 6 must fail closed")
