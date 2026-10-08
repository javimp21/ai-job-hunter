from types import SimpleNamespace

import pytest

from ai_job_hunter.claude_engine import QUESTION_KEYS, ClaudeJobDecisionEngine
from ai_job_hunter.decision_engine import FinalDecision, JobDecisionError, build_decision_contexts, evaluate_job_decision
from tests.test_candidate_prefilter import make_config, make_offer


def _tool_answer(**overrides):
    answer = {
        "role_relevance": {"probability": 0.9},
        "experience_accessibility": {"probability": 0.8},
        "backend_relevance": {"score": 3.6, "confidence": 0.9},
        "stack_transferability": {"probability": 0.85},
        "requirements_flexibility": {"probability": 0.7},
        "career_value": {"score": 3.0, "confidence": 0.7},
        "observable_role_quality": {"score": 3.2, "confidence": 0.8},
    }
    answer.update(overrides)
    return answer


class FakeClaude:
    def __init__(self, answer=None, fail=False):
        self.requests = []
        self.messages = SimpleNamespace(create=self._create)
        self._answer, self._fail = answer, fail

    def _create(self, **request):
        self.requests.append(request)
        if self._fail:
            raise RuntimeError("provider detail that must not leak")
        block = SimpleNamespace(type="tool_use", input=self._answer)
        return SimpleNamespace(content=[block], model="claude-haiku-5-5", usage=SimpleNamespace(input_tokens=3200, output_tokens=140))


def _context(sector="software"):
    config = make_config(preferences={"sector": sector, "remote_preference": "ANY"})
    return build_decision_contexts([make_offer(description="Build Python APIs. " * 80)], config)[0]


def test_the_answers_have_jevs_shape_and_the_policy_can_decide_with_them() -> None:
    client = FakeClaude(_tool_answer())
    engine = ClaudeJobDecisionEngine(client=client)

    evidence = engine.evaluate(_context())

    assert evidence.answers.role_relevance.value == 0.9 and evidence.answers.role_relevance.question_type == "noul"
    assert evidence.answers.backend_relevance.value == pytest.approx(0.9) and evidence.answers.backend_relevance.confidence == 0.9
    assert (evidence.input_tokens, evidence.output_tokens) == (3200, 140)
    assert engine.cache_identity == "claude/claude-haiku-5-5"
    result = evaluate_job_decision(_context(), engine)
    assert result.final_decision in set(FinalDecision)


def test_the_request_asks_all_seven_questions_with_the_sector_rubric_and_forces_the_tool() -> None:
    client = FakeClaude(_tool_answer())
    ClaudeJobDecisionEngine(client=client).evaluate(_context("finance"))

    request = client.requests[0]
    assert request["model"] == "claude-haiku-5-5" and request["tool_choice"]["name"] == "answer_questions"
    assert set(request["tools"][0]["input_schema"]["properties"]) == set(QUESTION_KEYS)
    assert "finance" in request["system"] and "score 4:" in request["system"]


def test_a_failing_or_malformed_provider_is_reported_without_details() -> None:
    with pytest.raises(JobDecisionError) as failed:
        ClaudeJobDecisionEngine(client=FakeClaude(fail=True)).evaluate(_context())
    assert "must not leak" not in str(failed.value)
    with pytest.raises(JobDecisionError):
        ClaudeJobDecisionEngine(client=FakeClaude(_tool_answer(backend_relevance={"score": 9, "confidence": 1}))).evaluate(_context())
    with pytest.raises(JobDecisionError):
        ClaudeJobDecisionEngine(client=FakeClaude({"role_relevance": {"probability": 1}})).evaluate(_context())
