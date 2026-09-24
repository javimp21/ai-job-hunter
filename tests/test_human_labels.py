from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ai_job_hunter.decision_engine import FinalDecision
from ai_job_hunter.human_labels import (
    HUMAN_LABELS_FORMAT,
    HumanLabelsError,
    HumanJobLabel,
    load_human_labels,
    measure_human_agreement,
)


def test_missing_local_human_labels_file_means_no_labels(tmp_path: Path) -> None:
    assert load_human_labels(tmp_path / "human-labels.local.json") == ()


def test_load_human_labels_schema_and_optional_notes(tmp_path: Path) -> None:
    path = tmp_path / "human-labels.local.json"
    path.write_text(
        json.dumps(
            {
                "format": HUMAN_LABELS_FORMAT,
                "version": 1,
                "labels": [
                    {"job_id": "greenhouse:123", "human_decision": "REVIEW", "notes": "Hybrid location."},
                    {"job_id": "lever:abc", "human_decision": "APPLY"},
                ],
            }
        ),
        encoding="utf-8",
    )

    labels = load_human_labels(path)

    assert labels == (
        HumanJobLabel(job_id="greenhouse:123", human_decision=FinalDecision.REVIEW, notes="Hybrid location."),
        HumanJobLabel(job_id="lever:abc", human_decision=FinalDecision.APPLY),
    )


def test_duplicate_human_job_ids_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "human-labels.local.json"
    path.write_text(
        json.dumps(
            {
                "format": HUMAN_LABELS_FORMAT,
                "version": 1,
                "labels": [
                    {"job_id": "same-job", "human_decision": "APPLY"},
                    {"job_id": "same-job", "human_decision": "SKIP"},
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(HumanLabelsError, match="unique job_id"):
        load_human_labels(path)


def test_human_agreement_reports_false_apply_and_false_skip() -> None:
    labels = (
        HumanJobLabel(job_id="a", human_decision=FinalDecision.APPLY),
        HumanJobLabel(job_id="b", human_decision=FinalDecision.SKIP),
        HumanJobLabel(job_id="c", human_decision=FinalDecision.REVIEW),
        HumanJobLabel(job_id="d", human_decision=FinalDecision.REVIEW),
    )

    result = measure_human_agreement(
        {
            "a": FinalDecision.SKIP,
            "b": FinalDecision.APPLY,
            "c": FinalDecision.REVIEW,
            "d": FinalDecision.SKIP,
        },
        labels,
    )

    assert result.compared == 4
    assert result.exact_matches == 1
    assert result.accuracy == pytest.approx(1 / 4)
    assert result.false_apply == 1
    assert result.false_skip == 1


def test_human_labels_file_name_is_ignored_by_git() -> None:
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not installed")
    root = Path(__file__).parents[1]

    result = subprocess.run(
        [
            git,
            "-c",
            f"safe.directory={root.as_posix()}",
            "check-ignore",
            "--quiet",
            "human-labels.local.json",
        ],
        cwd=root,
        check=False,
    )

    assert result.returncode == 0
