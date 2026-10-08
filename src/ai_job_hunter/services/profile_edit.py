"""/profile: change the answers given at sign-up (role, places, relocation, salary, offers without salary, mode, contracts).

The answers live in the person's stored profile (``preferences``), so an edit rewrites those fields and nothing else; the
experience read from the CV is untouched. Buttons carry ``pf:`` data; the text answers (role, places, salary) are read
while the person's onboarding state says ``edit``.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_job_hunter.candidates.profile import CandidateConfig
from ai_job_hunter.models.user import User, UserProfile
from ai_job_hunter.services.onboarding import (
    CONTRACT_ANSWERS,
    MODES,
    NO_SALARY_ANSWERS,
    SKIP_WORDS,
    WITHOUT_INTERNSHIPS,
    Button,
    Reply,
    parse_salary,
)
from ai_job_hunter.services.users import save_profile

# field -> button label
LABELS = {
    "role": "Puesto", "locations": "Lugares", "reloc": "Mudanza", "salary": "Sueldo",
    "nosalary": "Sin sueldo", "mode": "Modalidad", "contract": "Prácticas",
}
MODE_NAMES = {
    "REMOTE_ONLY": "remoto", "HYBRID_OR_REMOTE": "híbrido o remoto", "ONSITE_OR_HYBRID": "presencial o híbrido", "ANY": "me da igual",
}
_ASKS = {
    "role": "¿Qué puesto buscas? Por ejemplo: «Contable», «Backend Java», «Analista financiero».",
    "locations": "¿En qué ciudades o países trabajarías? Sepáralos con comas (por ejemplo: «Madrid, Barcelona, remoto en España»).",
    "salary": "¿Qué sueldo bruto anual esperas, como mínimo? Por ejemplo «30000», «30k €» o «saltar» para quitarlo.",
}


def is_editing(user: User) -> bool:
    return isinstance(user.onboarding, dict) and user.onboarding.get("step") == "edit"


def _preferences(session: Session, user: User) -> dict[str, Any] | None:
    profile = session.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    return dict(profile.config.get("preferences") or {}) if profile is not None else None


def _change(session: Session, user: User, **changes: Any) -> bool:
    profile = session.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    if profile is None:
        return False
    config = dict(profile.config)
    config["preferences"] = {**(config.get("preferences") or {}), **changes}
    save_profile(session, user, CandidateConfig.model_validate(config))
    return True


def menu(session: Session, user: User) -> Reply:
    prefs = _preferences(session, user)
    if prefs is None:
        return Reply("Todavía no tienes perfil: termina primero el alta.")
    salary = prefs.get("minimum_salary")
    internships = not prefs.get("acceptable_employment_types") or "INTERNSHIP" in prefs["acceptable_employment_types"]
    lines = [
        "Tus respuestas:",
        f"• Puesto: {', '.join(prefs.get('preferred_roles') or []) or '-'}",
        f"• Lugares: {', '.join(prefs.get('acceptable_locations') or []) or '-'}",
        f"• Mudarte a otro país: {'sí' if prefs.get('relocation_willingness') else 'no'}",
        f"• Sueldo mínimo: {salary + ' ' + str(prefs.get('salary_currency') or '') + '/' + str(prefs.get('salary_period') or '').lower() if salary else 'sin mínimo'}",
        f"• Ofertas sin sueldo publicado: {'sí' if prefs.get('accept_offers_without_salary', True) else 'no'}",
        f"• Modalidad: {MODE_NAMES.get(prefs.get('remote_preference', 'ANY'), '-')}",
        f"• Prácticas o becas: {'sí' if internships else 'no'}",
        "\n¿Qué quieres cambiar?",
    ]
    keys = list(LABELS)
    rows = tuple(
        tuple(Button(LABELS[key], f"pf:edit:{key}") for key in keys[start:start + 3]) for start in range(0, len(keys), 3)
    )
    return Reply("\n".join(lines), rows)


def press(session: Session, user: User, data: str) -> list[Reply]:
    parts = data.split(":")
    if len(parts) >= 3 and parts[1] == "edit" and parts[2] in LABELS:
        return _ask(user, parts[2])
    if len(parts) == 4 and parts[1] == "set":
        done = _set_choice(session, user, parts[2], parts[3])
        return [Reply("Hecho."), menu(session, user)] if done else [Reply("No he podido cambiarlo.")]
    return [menu(session, user)]


def _ask(user: User, field: str) -> list[Reply]:
    if field in _ASKS:
        user.onboarding = {"step": "edit", "field": field, "draft": {}}
        return [Reply(_ASKS[field])]
    choices = {
        "reloc": ("¿Te mudarías a otro país por una buena oferta?", (("Sí", "yes"), ("No", "no"))),
        "nosalary": (
            "¿Quieres recibir también ofertas que no publican el sueldo? Te llegarán más ofertas, pero no podemos "
            "asegurar que paguen lo que buscas.",
            (("Sí, mostrarlas", "yes"), ("No, solo con sueldo", "no")),
        ),
        "mode": (
            "¿Cómo quieres trabajar?",
            (("Remoto", "remote"), ("Híbrido o remoto", "hybrid"), ("Presencial o híbrido", "onsite"), ("Me da igual", "any")),
        ),
        "contract": ("¿Aceptarías prácticas o becas?", (("Sí, también", "yes"), ("No, solo trabajo", "no"))),
    }[field]
    text, options = choices
    rows = tuple((Button(label, f"pf:set:{field}:{value}"),) for label, value in options) if len(options) > 2 else (
        tuple(Button(label, f"pf:set:{field}:{value}") for label, value in options),
    )
    return [Reply(text, rows)]


def _set_choice(session: Session, user: User, field: str, value: str) -> bool:
    if field == "reloc" and value in {"yes", "no"}:
        return _change(session, user, relocation_willingness=value == "yes")
    if field == "nosalary" and f"ob:nosalary:{value}" in NO_SALARY_ANSWERS:
        return _change(session, user, accept_offers_without_salary=NO_SALARY_ANSWERS[f"ob:nosalary:{value}"])
    if field == "mode" and f"ob:mode:{value}" in MODES:
        return _change(session, user, remote_preference=MODES[f"ob:mode:{value}"])
    if field == "contract" and f"ob:contract:{value}" in CONTRACT_ANSWERS:
        accepted = CONTRACT_ANSWERS[f"ob:contract:{value}"]
        return _change(session, user, acceptable_employment_types=[] if accepted else list(WITHOUT_INTERNSHIPS))
    return False


def text(session: Session, user: User, message: str) -> list[Reply]:
    """The answer to the question asked by ``press``; anything unusable asks again."""

    field = (user.onboarding or {}).get("field")
    value = message.strip()
    if field == "role" and value:
        done = _change(session, user, preferred_roles=[value[:80]])
    elif field == "locations":
        places = [part.strip() for part in re.split(r"[,;\n]+", value) if part.strip()][:12]
        if not places:
            return [Reply("Dime al menos una ciudad o país.")]
        done = _change(session, user, preferred_locations=places, acceptable_locations=places)
    elif field == "salary":
        if value.casefold() in SKIP_WORDS:
            done = _change(session, user, minimum_salary=None)
        else:
            parsed = parse_salary(value)
            if parsed is None:
                return [Reply("No he entendido la cifra. Escribe algo como «30000», «30k €» o «saltar».")]
            done = _change(
                session, user, minimum_salary=parsed["amount"], salary_currency=parsed["currency"], salary_period=parsed["period"]
            )
    else:
        done = False
    user.onboarding = {"step": "done", "draft": {}}
    return [Reply("Hecho."), menu(session, user)] if done else [Reply("No he podido cambiarlo.")]
