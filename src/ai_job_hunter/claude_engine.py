"""A decision engine that asks a Claude model the same seven rubric questions Jev answers.

It exists to compare providers on the same offers (see ``scripts/compare_engines.py``): the answers keep Jev's shape (a
probability for the yes/no questions, a 0-4 score with a confidence for the scored ones), so the deterministic policy
that turns signals into APPLY/REVIEW/SKIP is the same for every provider. The rubric text comes from the sector
template, so each sector is asked in its own words.
"""

from __future__ import annotations

import json
from typing import Any

from ai_job_hunter.decision_engine import DecisionEvidence, JevAnswers, JevSignal, JobDecisionContext, JobDecisionError
from ai_job_hunter.jev import build_jev_state
from ai_job_hunter.rubric import rubric_spec_for_sector
from ai_job_hunter.services.cover_letters import CoverLetterError, _anthropic_client

DEFAULT_MODEL = "claude-haiku-5-5"
TOOL_NAME = "answer_questions"
QUESTION_KEYS = (
    "role_relevance",
    "experience_accessibility",
    "backend_relevance",
    "stack_transferability",
    "requirements_flexibility",
    "career_value",
    "observable_role_quality",
)

_SYSTEM = """You judge one job offer for one candidate. You get a JSON state with the candidate, the offer and the
deterministic checks already made. Answer every question independently by calling the tool once.

How to answer:
- yes/no questions ("probability"): the probability, from 0 to 1, that the answer is yes.
- scored questions ("score"): an integer-like score from 0 to 4 following the criteria given for that question, and a
  "confidence" from 0 to 1 for how well the offer text supports the score. Sparse or generic text means low confidence.
- Use only what the offer says. Do not use outside knowledge of the company. An unknown stays unknown: say so with
  low confidence instead of guessing.

The questions:
"""


class ClaudeJobDecisionEngine:
    """Provider-independent contract implementation (``JobDecisionEngine``) backed by a Claude model."""

    def __init__(self, *, model: str = DEFAULT_MODEL, client: Any | None = None) -> None:
        self.model = model
        self._client = client

    @property
    def cache_identity(self) -> str:
        return f"claude/{self.model}"

    def evaluate(self, context: JobDecisionContext) -> DecisionEvidence:
        sector = context.candidate.preferences.sector
        spec = rubric_spec_for_sector(sector)
        try:
            client = self._client or _anthropic_client()
            response = client.messages.create(**self.build_request(context, spec))
        except CoverLetterError:
            raise
        except Exception as error:  # noqa: BLE001 - provider errors never carry details worth echoing
            raise JobDecisionError(f"Claude request failed ({type(error).__name__}); no decision was cached.") from error
        try:
            payload = next(block.input for block in response.content if getattr(block, "type", "") == "tool_use")
            answers = _parse(payload, spec["question_types"])
            usage = response.usage
            return DecisionEvidence(
                answers=answers,
                model_version=str(getattr(response, "model", self.model)),
                engine_configuration=self.cache_identity,
                input_tokens=getattr(usage, "input_tokens", None),
                output_tokens=getattr(usage, "output_tokens", None),
            )
        except (StopIteration, AttributeError, KeyError, TypeError, ValueError) as error:
            raise JobDecisionError(f"Claude returned a malformed decision ({type(error).__name__}).") from error

    def build_request(self, context: JobDecisionContext, spec: dict[str, Any]) -> dict[str, Any]:
        lines = []
        for key in QUESTION_KEYS:
            lines.append(f"- {key} [{spec['question_types'][key]}]: {spec['questions'][key]}")
            if key in spec["score_criteria"]:
                lines += [f"    score {index}: {text}" for index, text in enumerate(spec["score_criteria"][key])]
        properties: dict[str, Any] = {}
        for key in QUESTION_KEYS:
            if spec["question_types"][key] == "noul":
                properties[key] = {
                    "type": "object",
                    "properties": {"probability": {"type": "number", "minimum": 0, "maximum": 1}},
                    "required": ["probability"],
                }
            else:
                properties[key] = {
                    "type": "object",
                    "properties": {
                        "score": {"type": "number", "minimum": 0, "maximum": 4},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["score", "confidence"],
                }
        return {
            "model": self.model,
            "max_tokens": 700,
            "system": _SYSTEM + "\n".join(lines),
            "messages": [{"role": "user", "content": json.dumps(build_jev_state(context), ensure_ascii=False)}],
            "tools": [{
                "name": TOOL_NAME,
                "description": "Return the answers to all seven questions.",
                "input_schema": {"type": "object", "properties": properties, "required": list(QUESTION_KEYS)},
            }],
            "tool_choice": {"type": "tool", "name": TOOL_NAME},
        }


def _parse(payload: dict[str, Any], types: dict[str, str]) -> JevAnswers:
    values: dict[str, JevSignal] = {}
    for key in QUESTION_KEYS:
        answer = payload[key]
        if types[key] == "noul":
            probability = float(answer["probability"])
            values[key] = JevSignal(question_type="noul", value=probability, raw_value=probability)
        else:
            score = float(answer["score"])
            if not 0 <= score <= 4:
                raise ValueError(f"{key} score out of range")
            values[key] = JevSignal(
                question_type="score", value=score / 4, confidence=float(answer["confidence"]), raw_value=score
            )
    return JevAnswers.model_validate(values)
