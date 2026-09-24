"""Local human decision labels and agreement metrics for offline evaluations."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ai_job_hunter.decision_engine import FinalDecision

DEFAULT_HUMAN_LABELS_PATH = Path("human-labels.local.json")
HUMAN_LABELS_FORMAT = "ai-job-hunter.human-labels"
HUMAN_LABELS_VERSION = 1


class HumanJobLabel(BaseModel):
    """One user-supplied label keyed by provider/external ID or another stable job ID."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    job_id: str = Field(min_length=1, max_length=1_024)
    human_decision: FinalDecision
    notes: str | None = Field(default=None, max_length=10_000)


class HumanLabelsDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format: Literal["ai-job-hunter.human-labels"]
    version: Literal[1]
    labels: tuple[HumanJobLabel, ...] = ()

    @model_validator(mode="after")
    def require_unique_job_ids(self) -> HumanLabelsDocument:
        identifiers = [label.job_id for label in self.labels]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("human labels must have unique job_id values")
        return self


class HumanLabelsError(ValueError):
    """A local human-label file could not be read or validated."""


class HumanAgreementSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    compared: int
    exact_matches: int
    accuracy: float | None
    false_apply: int
    false_skip: int
    confusion_matrix: dict[str, dict[str, int]]


def load_human_labels(
    path: str | Path = DEFAULT_HUMAN_LABELS_PATH,
) -> tuple[HumanJobLabel, ...]:
    """Load local labels; an absent file means that no human labels exist yet."""

    label_path = Path(path)
    if not label_path.exists():
        return ()
    try:
        payload = json.loads(label_path.read_text(encoding="utf-8"))
        document = HumanLabelsDocument.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as error:
        raise HumanLabelsError(f"Human-label file '{label_path}' is invalid: {error}") from error
    return document.labels


def measure_human_agreement(
    predictions: Mapping[str, FinalDecision | str],
    labels: Sequence[HumanJobLabel],
) -> HumanAgreementSummary:
    """Compare labeled IDs; false SKIP means a human-APPLY offer was skipped."""

    matrix = {
        human.value: {predicted.value: 0 for predicted in FinalDecision}
        for human in FinalDecision
    }
    exact_matches = 0
    false_apply = 0
    false_skip = 0
    compared = 0
    for label in labels:
        if label.job_id not in predictions:
            continue
        predicted = FinalDecision(predictions[label.job_id])
        matrix[label.human_decision.value][predicted.value] += 1
        compared += 1
        exact_matches += predicted is label.human_decision
        false_apply += predicted is FinalDecision.APPLY and label.human_decision is not FinalDecision.APPLY
        false_skip += predicted is FinalDecision.SKIP and label.human_decision is FinalDecision.APPLY
    return HumanAgreementSummary(
        compared=compared,
        exact_matches=exact_matches,
        accuracy=(exact_matches / compared) if compared else None,
        false_apply=false_apply,
        false_skip=false_skip,
        confusion_matrix=matrix,
    )
