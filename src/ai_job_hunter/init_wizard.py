"""Guided setup: ask a few questions and write a validated ``candidate.local.json``.

Interactive by default (``ai-job-hunter-init``) or non-interactive with ``--answers answers.json``
(the same keys as the questions below). The result is checked with the same model the hunter uses, so a
file written here always loads. Nothing is sent anywhere; the file stays on this machine.

Alert texts are still in Spanish; everything else (sources, filters, letters in the posting's language)
works for any candidate.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ai_job_hunter.candidates.profile import CandidateConfig

DEFAULT_OUTPUT = Path("candidate.local.json")

# key, question, kind, default shown to the user. kinds: text, list, number, bool, choice:<a|b>
QUESTIONS: tuple[tuple[str, str, str, str | None], ...] = (
    ("current_country", "Country you live in (as job sites write it, e.g. Spain, Germany)", "text", None),
    ("current_city", "City you live in", "text", None),
    ("years_of_experience", "Years of professional experience (0 if none)", "number", "0"),
    ("current_role", "Current or last role title (blank if none)", "text", ""),
    ("education", "Education (e.g. BSc Computer Science, 2026; blank to skip)", "text", ""),
    ("languages", "Languages you speak with level, comma-separated (e.g. Spanish (native), English (B2))", "list", None),
    ("preferred_roles", "Roles you are looking for, comma-separated (e.g. Backend Engineer, Data Analyst)", "list", None),
    ("primary_skills", "Your main skills, comma-separated", "list", ""),
    ("technologies", "Tools and technologies you have used, comma-separated (blank if not applicable)", "list", ""),
    ("willing_to_learn", "Tools you want to learn, comma-separated (blank to skip)", "list", ""),
    ("preferred_locations", "Where you would like to work first, comma-separated (cities or countries)", "list", None),
    ("acceptable_locations", "Other places you would accept, comma-separated (blank to skip)", "list", ""),
    ("relocation", "Would you move for a job?", "bool", "no"),
    ("relocation_destinations", "Countries you would gladly move to, comma-separated (blank to skip)", "list", ""),
    ("remote_preference", "Work mode", "choice:ANY|REMOTE_ONLY|HYBRID_OR_REMOTE|ONSITE_OR_HYBRID|ONSITE_ONLY", "ANY"),
    ("salary_currency", "Salary currency code (e.g. EUR, USD; blank for no salary filter)", "text", ""),
    ("minimum_salary", "Minimum salary per year in that currency (blank to skip)", "number", ""),
    ("target_salary", "Target salary per year (blank to skip)", "number", ""),
    ("minimum_seniority", "Lowest seniority you accept", "choice:INTERN|GRADUATE|JUNIOR|MID|SENIOR", "JUNIOR"),
    ("maximum_seniority", "Highest seniority you accept", "choice:JUNIOR|MID|SENIOR|STAFF|LEAD|MANAGER", "MID"),
    ("timezone", "Time zone (IANA name, e.g. Europe/Madrid, America/New_York)", "text", "UTC"),
    (
        "salary_guide",
        "Suggested salary answer per country, one 'Country: low-answer-high CUR' per entry separated by ';' "
        "(e.g. Spain: 28000-32000-34000 EUR; blank to skip)",
        "text",
        "",
    ),
)

_GUIDE_ENTRY = re.compile(r"^\s*([^:]+?)\s*:\s*(\d+)\s*-\s*(\d+)\s*-\s*(\d+)\s*([A-Za-z€$£]{1,5})\s*$")


class WizardError(ValueError):
    """A readable problem with the answers."""


def _split(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in re.split(r"[;,]", str(value or "")) if part.strip()] if value else []


def _split_languages(value: Any) -> list[str]:
    """Languages may carry a level in parentheses that contains commas-free text: split on commas outside them."""

    if isinstance(value, list):
        return _split(value)
    text = str(value or "")
    parts, depth, current = [], 0, ""
    for char in text:
        depth += {"(": 1, ")": -1}.get(char, 0)
        if char in ",;" and depth <= 0:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    return [part.strip() for part in parts if part.strip()]


def _number(value: Any) -> float | int | None:
    if value in (None, ""):
        return None
    try:
        number = float(str(value).replace(",", "."))
    except ValueError as error:
        raise WizardError(f"'{value}' is not a number") from error
    return int(number) if number == int(number) else number


def _parse_guide(value: Any) -> dict[str, dict[str, Any]]:
    if isinstance(value, dict):
        return value
    guide: dict[str, dict[str, Any]] = {}
    for part in [piece for piece in str(value or "").split(";") if piece.strip()]:
        match = _GUIDE_ENTRY.match(part)
        if match is None:
            raise WizardError(f"Cannot read salary guide entry '{part.strip()}'; use 'Country: low-answer-high CUR'")
        country, low, answer, high, currency = match.groups()
        guide[country] = {"low": int(low), "answer": int(answer), "high": int(high), "currency": currency.upper()}
    return guide


def build_config(answers: dict[str, Any]) -> CandidateConfig:
    """Turn answers into a validated config (raises WizardError with a readable message)."""

    country = str(answers.get("current_country") or "").strip()
    if not country:
        raise WizardError("current_country is required")
    languages = _split_languages(answers.get("languages"))
    roles = _split(answers.get("preferred_roles"))
    if not languages or not roles:
        raise WizardError("languages and preferred_roles are required")
    currency = str(answers.get("salary_currency") or "").strip().upper() or None
    minimum, target = _number(answers.get("minimum_salary")), _number(answers.get("target_salary"))
    relocation = answers.get("relocation")
    relocation = relocation if isinstance(relocation, bool) else str(relocation or "").strip().casefold() in {"y", "yes", "s", "si", "sí", "true", "1"}
    preferences: dict[str, Any] = {
        "preferred_roles": roles,
        "preferred_locations": _split(answers.get("preferred_locations")) or [country],
        "acceptable_locations": _split(answers.get("acceptable_locations")),
        "relocation_willingness": relocation,
        "relocation_preferred_locations": _split(answers.get("relocation_destinations")),
        "remote_preference": str(answers.get("remote_preference") or "ANY").strip().upper(),
        "preferred_technologies": _split(answers.get("technologies")),
        "willing_to_learn_technologies": _split(answers.get("willing_to_learn")),
        "minimum_seniority": str(answers.get("minimum_seniority") or "JUNIOR").strip().upper(),
        "maximum_seniority": str(answers.get("maximum_seniority") or "MID").strip().upper(),
        "international_remote_openness": True,
    }
    # Acceptable places include the preferred ones and the relocation destinations.
    acceptable = list(dict.fromkeys(
        [*preferences["preferred_locations"], *preferences["acceptable_locations"], *preferences["relocation_preferred_locations"]]
    ))
    preferences["acceptable_locations"] = acceptable
    if currency and (minimum is not None or target is not None):
        preferences.update(salary_currency=currency, salary_period="YEAR", minimum_salary=minimum, target_salary=target)
    profile: dict[str, Any] = {
        "years_of_experience": _number(answers.get("years_of_experience")) or 0,
        "current_role": str(answers.get("current_role") or "").strip() or None,
        "primary_skills": _split(answers.get("primary_skills")),
        "technologies": _split(answers.get("technologies")),
        "languages": languages,
        "education": str(answers.get("education") or "").strip() or None,
        "current_country": country,
        "current_city": str(answers.get("current_city") or "").strip() or None,
        "work_authorization": [country],
        "eligible_countries": [],
        "remote_work_capability": True,
    }
    payload = {
        "profile": {key: value for key, value in profile.items() if value not in (None, [])},
        "preferences": {key: value for key, value in preferences.items() if value not in (None, [])},
        "tuning": {"salary_guide": _parse_guide(answers.get("salary_guide"))},
    }
    try:
        return CandidateConfig.model_validate(payload)
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in error.errors()
        )
        raise WizardError(details) from error


def ask(input_fn: Callable[[str], str] = input, print_fn: Callable[..., None] = print) -> dict[str, Any]:
    """Interactive questions; a blank answer takes the default shown in brackets."""

    answers: dict[str, Any] = {}
    for key, question, kind, default in QUESTIONS:
        hint = f" [{default}]" if default else ""
        options = ""
        if kind.startswith("choice:"):
            options = " (" + ", ".join(kind.split(":", 1)[1].split("|")) + ")"
        while True:
            raw = input_fn(f"{question}{options}{hint}: ").strip()
            value = raw or (default or "")
            if kind.startswith("choice:") and value.upper() not in kind.split(":", 1)[1].split("|"):
                print_fn("  Please pick one of the listed options.")
                continue
            if kind == "number":
                try:
                    _number(value)
                except WizardError as error:
                    print_fn(f"  {error}")
                    continue
            if default is None and not value:
                print_fn("  This one is required.")
                continue
            answers[key] = value
            break
    return answers


def next_steps(config: CandidateConfig, timezone: str) -> str:
    return "\n".join(
        [
            "",
            "Next steps:",
            "  1. Put your CV in private/cv/ as CV_base_EN.md (and CV_base_ES.md or another language if you use it).",
            "  2. Copy .env.example to .env and set DATABASE_URL, ANTHROPIC_API_KEY (letters), TELEGRAM_BOT_TOKEN and",
            f"     TELEGRAM_CHAT_ID (alerts), and SCHEDULE_TIMEZONE={timezone}.",
            "  3. Create the database tables: alembic upgrade head",
            "  4. Add the companies and portals you care about (see docs/COMPANY_INTELLIGENCE.md and config/examples/).",
            "  5. Try it: ai-job-hunter run --dry-run",
            "",
            f"Profile written for a candidate in {config.profile.current_country} looking for: "
            + ", ".join(config.preferences.preferred_roles),
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a candidate.local.json from a few questions.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="file to write (default candidate.local.json)")
    parser.add_argument("--answers", type=Path, help="JSON file with the answers instead of asking")
    parser.add_argument("--force", action="store_true", help="overwrite an existing file")
    args = parser.parse_args(argv)
    if args.output.exists() and not args.force:
        print(f"{args.output} already exists; use --force to overwrite it.", file=sys.stderr)
        return 1
    try:
        if args.answers is not None:
            answers = json.loads(args.answers.read_text(encoding="utf-8"))
        else:
            print("A few questions to set up your profile. Press Enter to accept the value in brackets.\n")
            answers = ask()
        config = build_config(answers)
    except (OSError, ValueError) as error:  # json errors are ValueErrors
        print(f"Setup stopped: {error}", file=sys.stderr)
        return 2
    payload = config.model_dump(mode="json", exclude_none=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {args.output}.")
    print(next_steps(config, str(answers.get("timezone") or "UTC")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
