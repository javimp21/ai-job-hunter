"""Sign-up by invitation as a conversation (docs/ONBOARDING_DESIGN.md).

The flow does not know Telegram: it receives events (a text, a button press, a CV) and returns replies (text plus
buttons) that the bot sends. Steps: consent, CV, confirm the profile read from it, sector, wanted role, places,
relocation, salary and work mode; then the validated profile is stored and the trial starts. The CV itself is never
stored: only the profile the person confirms.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_job_hunter.candidates.profile import CandidateConfig
from ai_job_hunter.models.user import Invitation, User, UserProfile, UserStatus
from ai_job_hunter.sectors.engine import SECTORS_DIR, get_template
from ai_job_hunter.services.users import save_profile

PRIVACY_VERSION = "2026-10-draft1"
TRIAL_DAYS = 7
INVITATION_DAYS = 7
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L
MIN_CV_TEXT_CHARS = 300
# Flip to True when the per-user evaluation and alert loop exists (plan phase 3); until then the bot must not promise alerts.
ALERTS_LIVE = True
SKIP_WORDS = {"saltar", "paso", "no", "ninguno", "omitir", "skip"}


@dataclass(frozen=True, slots=True)
class Button:
    label: str
    data: str


@dataclass(frozen=True, slots=True)
class Reply:
    text: str
    buttons: tuple[tuple[Button, ...], ...] = ()


@dataclass(frozen=True, slots=True)
class Event:
    kind: str  # "text" | "press" | "document"
    text: str = ""
    data: str = ""
    filename: str = ""
    content: bytes | None = None


# (cv_text or None, (filename, bytes) or None, previous draft or None, correction or None) -> draft profile dict
ProfileExtractor = Callable[[str | None, tuple[str, bytes] | None, dict[str, Any] | None, str | None], dict[str, Any]]


class OnboardingError(RuntimeError):
    """A safe, user-readable failure."""


# --- invitations ------------------------------------------------------------------------------------------------------


def create_invitation(session: Session, owner: User, *, now: datetime | None = None) -> Invitation:
    current = now or datetime.now(UTC)
    invitation = Invitation(
        code="".join(secrets.choice(CODE_ALPHABET) for _ in range(8)),
        created_by_user_id=owner.id,
        expires_at=current + timedelta(days=INVITATION_DAYS),
    )
    session.add(invitation)
    session.flush()
    return invitation


def redeem_invitation(
    session: Session, code: str, chat_id: str, *, now: datetime | None = None
) -> tuple[User | None, str]:
    """Create the person's account from an invitation. Returns (user, "new"|"existing") or (None, reason)."""

    current = now or datetime.now(UTC)
    existing = session.scalar(select(User).where(User.telegram_chat_id == chat_id))
    if existing is not None:
        return existing, "existing"
    invitation = session.scalar(select(Invitation).where(Invitation.code == code.strip().upper()))
    if invitation is None:
        return None, "unknown"
    if invitation.used_at is not None:
        return None, "used"
    if _aware(invitation.expires_at) < current:
        return None, "expired"
    user = User(
        telegram_chat_id=chat_id, language="es", timezone="Europe/Madrid", status=UserStatus.ONBOARDING.value,
        is_owner=False, onboarding={"step": "consent", "draft": {}},
    )
    session.add(user)
    session.flush()
    invitation.used_by_user_id = user.id
    invitation.used_at = current
    session.flush()
    return user, "new"


# --- the conversation -------------------------------------------------------------------------------------------------


def welcome(user: User) -> list[Reply]:
    return [
        Reply(
            "👋 Soy Job Hunter: leo ofertas de empleo de miles de empresas y te aviso solo de las que encajan contigo.\n\n"
            "Esto es una beta cerrada, gratis durante unos días. Antes de empezar, lo que tienes que saber:\n"
            "• Te pediré tu CV. No guardo el archivo: lo leo una vez y guardo tu perfil y un resumen de tu experiencia, "
            "sin nombre ni contacto, para escribir tus cartas. Tú lo confirmas.\n"
            "• Para leerlo uso un modelo de IA de Anthropic: el texto de tu CV se envía a ese proveedor.\n"
            "• Para valorar cada oferta envío tu perfil resumido (puesto, años de experiencia, habilidades, país) y el texto "
            "de la oferta a otro proveedor de IA (TypeSafe), nunca tu nombre ni tu contacto.\n"
            "• Guardo tu perfil, las ofertas que te aviso y tus votos y notas, para mejorar tus avisos. "
            "Está en un servidor en la nube; al borrarlo, las copias de seguridad lo eliminan en un máximo de 14 días.\n"
            "• Puedes ver todo con /my_data, pausar con /pause y borrarlo todo con /erase.\n"
            "• No envío nada a nadie en tu nombre ni me presento a ninguna oferta.\n\n"
            "¿Aceptas?",
            ((Button("✅ Acepto", "ob:consent:yes"), Button("No acepto", "ob:consent:no")),),
        )
    ]


def handle(
    session: Session, user: User, event: Event, extract: ProfileExtractor, *, now: datetime | None = None
) -> list[Reply]:
    """Advance the sign-up by one event and return what to say; commits nothing (the caller does)."""

    current = now or datetime.now(UTC)
    state = dict(user.onboarding or {"step": "consent", "draft": {}})
    step = state.get("step", "consent")
    draft = dict(state.get("draft") or {})

    def move(new_step: str, new_draft: dict[str, Any] | None = None) -> None:
        user.onboarding = {"step": new_step, "draft": new_draft if new_draft is not None else draft}

    if event.kind == "press" and event.data.startswith("ob:consent:") and step == "consent":
        if event.data.endswith("no"):
            session.delete(user)
            session.flush()
            return [Reply("Sin problema, no guardo nada. Si cambias de idea, pide otra invitación.")]
        user.consent_at, user.consent_version = current, PRIVACY_VERSION
        move("cv")
        return [Reply("Perfecto. Envíame tu CV en PDF o Word (o pega su texto). Lo leo una vez y no lo guardo.")]

    if step == "consent":
        return welcome(user)

    if step == "cv":
        if event.kind == "document" and event.content:
            return _read_cv(user, extract, move, None, (event.filename, event.content), None, None)
        if event.kind == "text" and len(event.text) >= MIN_CV_TEXT_CHARS:
            return _read_cv(user, extract, move, event.text, None, None, None)
        return [Reply("Envíame tu CV como archivo PDF o Word, o pega aquí su texto completo.")]

    if step == "confirm":
        if event.kind == "press" and event.data == "ob:confirm:yes":
            move("sector")
            return [_sector_question()]
        if event.kind == "press" and event.data == "ob:confirm:fix":
            move("correct")
            return [Reply("Dime qué hay que corregir, con tus palabras (por ejemplo: «llevo 3 años, no 2, y también sé Kotlin»).")]
        return [_summary(draft)]

    if step == "correct":
        if event.kind == "text" and event.text.strip():
            return _read_cv(user, extract, move, None, None, draft, event.text.strip())
        return [Reply("Escríbeme la corrección.")]

    if step == "sector":
        sector = event.data.removeprefix("ob:sector:") if event.kind == "press" and event.data.startswith("ob:sector:") else None
        if sector in available_sectors():
            draft["sector"] = sector
            move("role", draft)
            return [Reply("¿Qué puesto buscas? Por ejemplo: «Contable», «Backend Java», «Analista financiero».")]
        return [_sector_question()]

    if step == "role":
        if event.kind == "text" and event.text.strip():
            draft["role"] = event.text.strip()[:80]
            move("locations", draft)
            return [Reply("¿En qué ciudades o países trabajarías? Sepáralos con comas (por ejemplo: «Madrid, Barcelona, remoto en España»).")]
        return [Reply("Escribe el puesto que buscas.")]

    if step == "locations":
        if event.kind == "text" and event.text.strip():
            draft["locations"] = [part.strip() for part in re.split(r"[,;\n]+", event.text) if part.strip()][:12]
            move("relocation", draft)
            return [Reply("¿Te mudarías a otro país por una buena oferta?", ((Button("Sí", "ob:reloc:yes"), Button("No", "ob:reloc:no")),))]
        return [Reply("Dime al menos una ciudad o país.")]

    if step == "relocation":
        if event.kind == "press" and event.data in {"ob:reloc:yes", "ob:reloc:no"}:
            draft["relocation"] = event.data.endswith("yes")
            move("salary", draft)
            return [Reply("¿Qué sueldo bruto anual esperas, como mínimo? Por ejemplo «30000», «30k €» o «saltar».")]
        return [Reply("Elige una opción.", ((Button("Sí", "ob:reloc:yes"), Button("No", "ob:reloc:no")),))]

    if step == "salary":
        if event.kind == "text":
            if event.text.strip().casefold() in SKIP_WORDS:
                move("mode", draft)
                return [_mode_question()]
            parsed = parse_salary(event.text)
            if parsed is not None:
                draft["salary"] = parsed
                move("mode", draft)
                return [_mode_question()]
        return [Reply("No he entendido la cifra. Escribe algo como «30000», «30k €» o «saltar».")]

    if step == "mode":
        modes = {"ob:mode:remote": "REMOTE_ONLY", "ob:mode:hybrid": "HYBRID_OR_REMOTE",
                 "ob:mode:onsite": "ONSITE_OR_HYBRID", "ob:mode:any": "ANY"}
        if event.kind == "press" and event.data in modes:
            draft["remote_preference"] = modes[event.data]
            return _finish(session, user, draft, current)
        return [_mode_question()]

    return [Reply("Ya tienes tu perfil. Usa /my_data, /pause, /resume o /erase.")]


# --- steps' helpers ---------------------------------------------------------------------------------------------------


def _read_cv(user, extract, move, text, file, previous, correction) -> list[Reply]:
    try:
        draft = extract(text, file, previous, correction)
    except Exception:  # noqa: BLE001 - the person sees a safe message, never a provider error
        return [Reply("No he podido leer el CV. Prueba con otro archivo o pega su texto.")]
    merged = {**(previous or {}), **draft}
    move("confirm", merged)
    return [_summary(merged)]


def _summary(draft: dict[str, Any]) -> Reply:
    def line(label: str, key: str) -> str | None:
        value = draft.get(key)
        if not value:
            return None
        return f"• {label}: {', '.join(value) if isinstance(value, list) else value}"

    lines = [
        line("Puesto actual", "current_role"), line("Años de experiencia", "years_of_experience"),
        line("Habilidades", "primary_skills"), line("Herramientas", "technologies"), line("Idiomas", "languages"),
        line("Formación", "education"), line("Ubicación", "current_city"),
    ]
    body = "\n".join(item for item in lines if item) or "• (no he encontrado datos claros)"
    kept = (
        "\n\nTambién guardaré un resumen de tu experiencia (sin nombre ni contacto) para escribir tus cartas; "
        "lo verás completo con /my_data y se borra con /erase."
        if draft.get("professional_summary")
        else ""
    )
    return Reply(
        f"Esto es lo que he leído de tu CV:\n{body}{kept}\n\n¿Es correcto?",
        ((Button("✅ Es correcto", "ob:confirm:yes"), Button("✏️ Corregir", "ob:confirm:fix")),),
    )


def available_sectors() -> dict[str, str]:
    return {path.stem: get_template(path.stem).template.label for path in sorted(SECTORS_DIR.glob("*.json"))}


def _sector_question() -> Reply:
    buttons = tuple((Button(label, f"ob:sector:{sector_id}"),) for sector_id, label in available_sectors().items())
    return Reply("¿En qué sector buscas trabajo?", buttons)


def _mode_question() -> Reply:
    return Reply(
        "¿Cómo quieres trabajar?",
        (
            (Button("Remoto", "ob:mode:remote"), Button("Híbrido o remoto", "ob:mode:hybrid")),
            (Button("Presencial o híbrido", "ob:mode:onsite"), Button("Me da igual", "ob:mode:any")),
        ),
    )


def parse_salary(text: str) -> dict[str, Any] | None:
    """A yearly (or monthly) figure from free text: «30000», «30k €», «2.500 € al mes», «40.000 USD»."""

    lowered = text.casefold()
    match = re.search(r"(\d[\d.,]*)\s*(k|mil)?", lowered)
    if not match:
        return None
    raw = match.group(1)
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", raw):
        raw = raw.replace(".", "")
    elif re.fullmatch(r"\d{1,3}(,\d{3})+", raw):
        raw = raw.replace(",", "")
    else:
        raw = raw.replace(",", ".")
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        return None
    if match.group(2):
        amount *= 1000
    if amount <= 0 or amount > 10_000_000:
        return None
    currency = "USD" if ("$" in text or "usd" in lowered) else "GBP" if ("£" in text or "gbp" in lowered) else "EUR"
    period = "MONTH" if re.search(r"mes|month|mensual", lowered) else "YEAR"
    return {"amount": str(amount), "currency": currency, "period": period}


def build_config(draft: dict[str, Any]) -> CandidateConfig:
    """The validated profile from what the CV said and the person answered."""

    years = draft.get("years_of_experience")
    try:
        years_number = Decimal(str(years)) if years not in (None, "") else None
    except InvalidOperation:
        years_number = None
    profile: dict[str, Any] = {
        "years_of_experience": years_number,
        "current_role": draft.get("current_role") or None,
        "primary_skills": list(draft.get("primary_skills") or []),
        "secondary_skills": list(draft.get("secondary_skills") or []),
        "technologies": list(draft.get("technologies") or []),
        "languages": list(draft.get("languages") or []),
        "education": draft.get("education") or None,
        "current_country": draft.get("current_country") or None,
        "current_city": draft.get("current_city") or None,
        "remote_work_capability": True,
    }
    locations = list(draft.get("locations") or [])
    preferences: dict[str, Any] = {
        "sector": draft.get("sector", "software"),
        "preferred_roles": [draft["role"]] if draft.get("role") else [],
        "preferred_locations": locations,
        "acceptable_locations": locations,
        "relocation_willingness": bool(draft.get("relocation")),
        "remote_preference": draft.get("remote_preference", "ANY"),
    }
    if years_number is not None:
        preferences["maximum_seniority"] = "MID" if years_number < 2 else "SENIOR" if years_number < 6 else "HEAD"
    salary = draft.get("salary")
    if salary:
        preferences.update(
            minimum_salary=Decimal(salary["amount"]), salary_currency=salary["currency"], salary_period=salary["period"]
        )
    return CandidateConfig.model_validate({"profile": {k: v for k, v in profile.items() if v not in (None, [])},
                                           "preferences": preferences})


def _finish(session: Session, user: User, draft: dict[str, Any], now: datetime) -> list[Reply]:
    try:
        config = build_config(draft)
    except ValueError:
        user.onboarding = {"step": "cv", "draft": {}}
        return [Reply("Algo no cuadra en tu perfil y tengo que empezar de nuevo con el CV. Envíamelo otra vez.")]
    save_profile(session, user, config, cv_text=draft.get("professional_summary"))
    user.status = UserStatus.ACTIVE.value
    user.trial_started_at, user.trial_ends_at = now, now + timedelta(days=TRIAL_DAYS)
    user.onboarding = {"step": "done", "draft": {}}
    session.flush()
    if ALERTS_LIVE:
        return [
            Reply(
                "🎉 Listo. A partir de ahora te aviso de las ofertas nuevas que encajen contigo.\n"
                f"La prueba gratuita dura {TRIAL_DAYS} días. Puedes votar cada aviso con 👍/👎 y escribir tu opinión "
                "respondiendo al mensaje: así los avisos mejoran.\n\n"
                "/my_data: ver lo que guardo · /pause: pausar · /erase: borrar todo."
            )
        ]
    return [
        Reply(
            "✅ Perfil guardado. Los avisos todavía no están activados para ti: estoy terminando esa parte de la beta "
            "y te escribiré aquí cuando empiecen. Tu prueba de "
            f"{TRIAL_DAYS} días empezará entonces.\n\n"
            "/my_data: ver lo que guardo · /pause: pausar · /erase: borrar todo."
        )
    ]


# --- commands for any registered person ------------------------------------------------------------------------------


def my_data(session: Session, user: User) -> Reply:
    from ai_job_hunter.services.user_erasure import count_user_rows

    profile = session.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    lines = [f"Estado: {user.status}", f"Consentimiento: {user.consent_at:%Y-%m-%d} (aviso {user.consent_version})" if user.consent_at else "Consentimiento: pendiente"]
    if user.trial_ends_at:
        lines.append(f"Prueba hasta: {user.trial_ends_at:%Y-%m-%d}")
    if profile is not None:
        prefs = profile.config.get("preferences", {})
        prof = profile.config.get("profile", {})
        lines += [
            f"Sector: {profile.sector}", f"Puesto actual: {prof.get('current_role') or '-'}",
            f"Puesto buscado: {', '.join(prefs.get('preferred_roles') or []) or '-'}",
            f"Lugares: {', '.join(prefs.get('acceptable_locations') or []) or '-'}",
            f"Modalidad: {prefs.get('remote_preference', '-')}", f"Idiomas: {', '.join(prof.get('languages') or []) or '-'}",
        ]
        if profile.cv_text:
            lines.append(f"\nResumen de tu experiencia (lo uso para escribir tus cartas):\n{profile.cv_text}\n")
    counts = count_user_rows(session, user)
    stored = ", ".join(f"{label} {n}" for label, n in counts.items() if n)
    lines.append(f"Guardado: {stored or 'nada más'}")
    lines.append("\nNo guardo el archivo de tu CV. /erase elimina todo esto.")
    return Reply("\n".join(lines))


COMMAND_ALIASES = {"/mis_datos": "/my_data", "/pausa": "/pause", "/reanudar": "/resume", "/borrar": "/erase", "/invitar": "/invite"}


def handle_command(session: Session, user: User, text: str) -> list[Reply]:
    command = text.strip().split()[0].casefold() if text.strip() else ""
    command = COMMAND_ALIASES.get(command, command)
    if command == "/my_data":
        return [my_data(session, user)]
    if command == "/pause":
        user.status = UserStatus.PAUSED.value
        return [Reply("Pausado: no te mandaré más avisos. /resume los activa de nuevo.")]
    if command == "/resume":
        if user.status == UserStatus.PAUSED.value:
            user.status = UserStatus.ACTIVE.value
            return [Reply("Reanudado. Vuelvo a avisarte de las ofertas nuevas.")]
        return [Reply("No estabas en pausa.")]
    if command == "/erase":
        return [Reply(
            "Esto borra tu perfil, tus votos, notas y todos tus avisos, y no se puede deshacer. ¿Seguro?",
            ((Button("Sí, borrar todo", "ob:erase:yes"), Button("Cancelar", "ob:erase:no")),),
        )]
    return []


def handle_erase_press(session: Session, user: User, data: str) -> list[Reply]:
    from ai_job_hunter.services.user_erasure import erase_user

    if data == "ob:erase:yes":
        erase_user(session, user)
        return [Reply("Hecho: he borrado todos tus datos. Si vuelves, necesitarás una invitación nueva.")]
    return [Reply("Cancelado, no he borrado nada.")]


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
