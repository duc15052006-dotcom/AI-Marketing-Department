from datetime import datetime, timezone

from runtime.research_loop import BoundedResearchLoop, build_research_plan, infer_language
from tools.receipts import ExecutionMode, ExecutionReceipt, ExecutionStatus


class FakeGateway:
    def __init__(self):
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        now = datetime.now(timezone.utc)
        if request.capability_id == "web_search":
            idx = len([r for r in self.requests if r.capability_id == "web_search"])
            return ExecutionReceipt(
                run_id=request.run_id,
                agent_id=request.agent_id,
                capability_id="web_search",
                provider="fake_search",
                request_hash=request.calculate_request_hash(),
                started_at=now,
                completed_at=now,
                status=ExecutionStatus.SUCCESS,
                execution_mode=ExecutionMode.REAL,
                data={"results": [{"title": "s", "snippet": "discovery only", "url": f"https://example.com/{idx}"}]},
            )
        return ExecutionReceipt(
            run_id=request.run_id,
            agent_id=request.agent_id,
            capability_id="read_page",
            provider="fake_reader",
            request_hash=request.calculate_request_hash(),
            started_at=now,
            completed_at=now,
            status=ExecutionStatus.SUCCESS,
            execution_mode=ExecutionMode.REAL,
            data={"url": request.parameters["url"], "extracted_text": "source body"},
        )


def test_vietnamese_language_and_deep_plan_are_bounded():
    assert infer_language("nghiên cứu mức độ tăng trưởng ngành decor") == "vi"
    plan = build_research_plan("nghiên cứu mức độ tăng trưởng ngành decor", "DEEP")
    assert plan.language == "vi"
    assert len(plan.queries) == 5
    assert plan.max_page_reads == 8
    assert plan.queries[0] == "nghiên cứu mức độ tăng trưởng ngành decor"
    assert any("phản biện" in q for q in plan.queries)


def test_standard_loop_multi_searches_then_reads_unique_real_sources():
    gateway = FakeGateway()
    run = BoundedResearchLoop(gateway).execute(
        run_id="RUN-1",
        agent_id="intelligence",
        objective="decor market growth",
        business_id="BIZ",
        project_id=None,
        chat_id="CHAT",
        depth="STANDARD",
    )
    assert len(run.search_receipts) == 3
    assert len(run.page_receipts) == 3
    assert run.real_page_count == 3
    assert all(req.parameters.get("language") == "en" for req in gateway.requests if req.capability_id == "web_search")
    rendered = run.render_page_context()
    assert "Search snippets are discovery signals only" in rendered
    assert "source body" in rendered


def test_deep_loop_never_searches_literal_vague_followup_when_resolved_objective_given():
    gateway = FakeGateway()
    objective = "nghiên cứu mức độ tăng trưởng ngành decor\n\nYêu cầu tiếp nối: nghiên cứu sâu hơn"
    BoundedResearchLoop(gateway).execute(
        run_id="RUN-2", agent_id="intelligence", objective=objective,
        business_id="BIZ", project_id=None, chat_id="CHAT", depth="DEEP",
    )
    search_queries = [r.parameters["query"] for r in gateway.requests if r.capability_id == "web_search"]
    assert len(search_queries) == 5
    assert all(q.strip().lower() != "tìm kỹ cho tôi" for q in search_queries)
