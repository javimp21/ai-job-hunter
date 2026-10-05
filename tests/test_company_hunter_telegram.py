from datetime import UTC, datetime
from uuid import uuid4

import pytest
from company_hunter_support import add_company, add_contact, scripted_client, write_private
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_job_hunter.company_hunter.bot import build_handlers
from ai_job_hunter.company_hunter.notify import (
    CONNECTION_ACCEPTED_PREFIX,
    CONNECTION_SENT_PREFIX,
    CONNECTION_SKIP_PREFIX,
    HUNTER_DRAFT_PREFIX,
    connection_keyboard,
    connection_message,
    format_drafts,
    send_connections,
    weekly_message,
)
from ai_job_hunter.company_hunter.queue import suggest_connections
from ai_job_hunter.company_hunter.ranking import rank_companies
from ai_job_hunter.models import ConnectionRequest
from ai_job_hunter.services.notifications import TelegramAmbiguousError, TelegramRejectedError, TelegramSendResult
from ai_job_hunter.services.telegram_bot import handle_update
from company_hunter_support import drafts_json

CHAT = "4242"
MONDAY = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)


class FakeBot:
    def __init__(self):
        self.events = []

    def answer_callback_query(self, callback_id, text):
        self.events.append(("answer", text))

    def send_text(self, text, reply_markup=None, reply_to=None):
        self.events.append(("send", text, reply_to))


class FakeProvider:
    def __init__(self, fail=None):
        self.messages = []
        self.fail = fail or {}

    def send_message(self, message, *, reply_markup=None):
        self.messages.append((message, reply_markup))
        error = self.fail.get(len(self.messages))
        if error:
            raise error
        return TelegramSendResult(message_id=str(100 + len(self.messages)))


def callback(data, message_id=7):
    return {"update_id": 1, "callback_query": {"id": "cb", "data": data, "message": {"chat": {"id": 4242}, "message_id": message_id}}}


def reply(text, to, *, chat=4242):
    return {"update_id": 2, "message": {"chat": {"id": chat}, "message_id": 55, "text": text, "reply_to_message": {"message_id": to}}}


def factory(session):
    """A fresh session per request on the same in-memory database, like the real bot."""

    bind = session.get_bind()
    return lambda: Session(bind)


@pytest.fixture
def world(db_session, tmp_path):
    company = add_company(db_session, "Acme Pay")
    contact = add_contact(
        db_session, company, "Jane <Doe>", "Engineering Manager", "ENGINEERING_MANAGER",
        linkedin_url="https://linkedin.com/in/jane-doe-1",
    )
    nolink = add_contact(db_session, company, "Eng Ineer", "Backend Engineer", "ENGINEER")
    db_session.commit()
    cv_dir, style = write_private(tmp_path)
    return company, contact, nolink, cv_dir, style


def suggestions(session, world, note="Hola, vi Acme Pay y su Java; yo uso Java y Kafka en banca.", count=5):
    _company, _contact, _nolink, cv_dir, style = world
    client, _ = scripted_client(note)
    result = suggest_connections(
        session, rank_companies(session).ranked, client=client, now=MONDAY, target=count, cv_dir=cv_dir, style_guide_path=style
    )
    session.commit()
    return result


def test_weekly_message_lists_top_five_with_reasons_contact_status_and_buttons(db_session, world):
    company, contact, *_ = world
    others = [add_company(db_session, f"Other {n}", website=f"https://o{n}.example.test") for n in range(6)]
    db_session.commit()
    fits = list(rank_companies(db_session).ranked)

    text, keyboard = weekly_message(fits, {company.id: contact}, week_label="2026-W41")

    assert text.count("<b>") >= 6 and "🏹" in text and "Company Hunter" in text
    assert "Por qué:" in text and "sin contacto verificado" in text
    assert "Jane &lt;Doe&gt;" in text and "<Doe>" not in text  # escaped
    assert "prioridad de revisión, no probabilidad" in text and "No se envía nada" in text
    buttons = keyboard["inline_keyboard"][0]
    assert [b["text"] for b in buttons] == ["✍️ 1", "✍️ 2", "✍️ 3", "✍️ 4", "✍️ 5"]
    assert len(others) + 1 > 5
    assert all(b["callback_data"].startswith(HUNTER_DRAFT_PREFIX) and len(b["callback_data"].encode()) <= 64 for b in buttons)


def test_weekly_message_with_no_companies_has_no_buttons():
    text, keyboard = weekly_message([], {}, week_label="2026-W41")
    assert keyboard is None and "No hay empresas" in text


def test_connection_message_shows_linkedin_only_when_a_public_page_linked_it(db_session, world):
    company, contact, nolink, *_ = world
    result = suggestions(db_session, world)
    by_contact = {r.contact_id: r for r in result.new}

    linked = connection_message(1, 2, by_contact[contact.id], contact, company)
    plain = connection_message(2, 2, by_contact[nolink.id], nolink, company)

    assert "https://linkedin.com/in/jane-doe-1" in linked
    assert "linkedin.com" not in plain and "Búscalo en LinkedIn: Eng Ineer Acme Pay" in plain
    assert f"Nota ({len(by_contact[nolink.id].note)}/300" in plain and "<code>" in plain
    keyboard = connection_keyboard(by_contact[nolink.id].id)["inline_keyboard"][0]
    assert [b["text"] for b in keyboard] == ["✅ Enviada", "🤝 Aceptó", "⏭️ Saltar"]
    assert all(len(b["callback_data"].encode()) <= 64 for b in keyboard)


def test_send_connections_sends_one_message_per_person_once_and_stores_ids(db_session, world):
    result = suggestions(db_session, world)
    provider = FakeProvider()

    first = send_connections(db_session, provider, result.today, now=MONDAY, day_label="2026-10-05")
    db_session.commit()
    second = send_connections(db_session, provider, result.today, now=MONDAY, day_label="2026-10-05")

    assert first.sent == 2 and second.sent == 0
    assert len(provider.messages) == 3  # header + two people; nothing on the second call
    assert "conexión manual" in provider.messages[0][0].casefold() or "Conexión manual" in provider.messages[0][0]
    ids = {r.telegram_message_id for r in db_session.scalars(select(ConnectionRequest))}
    assert ids == {"102", "103"}


def test_delivery_failures_are_recorded_without_duplicate_sends(db_session, world):
    result = suggestions(db_session, world)
    provider = FakeProvider(fail={2: TelegramAmbiguousError(), 3: TelegramRejectedError(400)})

    delivery = send_connections(db_session, provider, result.today, now=MONDAY, day_label="d")

    assert delivery.sent == 0 and len(delivery.failed) == 2
    rows = {r.contact.name: r.telegram_message_id for r in result.today}
    assert sorted(rows.values(), key=str) == [None, "unknown"]  # ambiguous never retried; rejected can retry


def test_draft_button_replies_with_both_variants_and_nothing_is_sent_out(db_session, world, tmp_path):
    company, *_rest, cv_dir, style = world
    client, messages = scripted_client(drafts_json())
    handlers = build_handlers(factory(db_session), client=client, cv_dir=cv_dir, style_guide_path=style)
    bot = FakeBot()

    outcome = handle_update(
        callback(f"{HUNTER_DRAFT_PREFIX}{company.id}"), chat_id=CHAT, bot=bot, generate=None, generated={}, hunter=handlers
    )
    again = handle_update(
        callback(f"{HUNTER_DRAFT_PREFIX}{company.id}"), chat_id=CHAT, bot=bot, generate=None, generated={}, hunter=handlers
    )

    assert outcome == again == "generated" and len(messages.requests) == 1
    assert bot.events[0] == ("answer", "Preparando borradores…")
    sent = [event for event in bot.events if event[0] == "send"][0]
    assert sent[2] == 7  # delivered as a reply to the weekly message
    assert "— Email —" in sent[1] and "— LinkedIn DM —" in sent[1] and "no se ha enviado nada a la empresa" in sent[1]


def test_draft_button_errors_are_reported_not_raised(db_session, world, tmp_path):
    company, *_ = world
    handlers = build_handlers(factory(db_session), client=scripted_client(drafts_json())[0], cv_dir=tmp_path / "none")
    bot = FakeBot()

    outcome = handle_update(
        callback(f"{HUNTER_DRAFT_PREFIX}{company.id}"), chat_id=CHAT, bot=bot, generate=None, generated={}, hunter=handlers
    )

    assert outcome == "failed" and "Base CV" in bot.events[-1][1]


def test_connection_buttons_update_state_and_accept_replies_with_a_follow_up(db_session, world):
    result = suggestions(db_session, world, count=1)
    request = result.new[0]
    *_, cv_dir, style = world
    client, messages = scripted_client("Gracias por aceptar! Me interesa lo que hacéis en Acme Pay con Java.")
    handlers = build_handlers(factory(db_session), client=client, cv_dir=cv_dir, style_guide_path=style)
    bot = FakeBot()

    def tap(prefix):
        return handle_update(
            callback(f"{prefix}{request.id}", message_id=9), chat_id=CHAT, bot=bot, generate=None, generated={}, hunter=handlers
        )

    assert tap(CONNECTION_SENT_PREFIX) == "connection"
    db_session.expire_all()
    assert db_session.get(ConnectionRequest, request.id).status == "SENT"
    assert db_session.get(ConnectionRequest, request.id).sent_at is not None
    assert tap(CONNECTION_ACCEPTED_PREFIX) == "connection"
    db_session.expire_all()
    assert db_session.get(ConnectionRequest, request.id).status == "ACCEPTED"
    follow_up = [e for e in bot.events if e[0] == "send"][0]
    assert "Gracias por aceptar" in follow_up[1] and follow_up[2] == 9 and "a mano" in follow_up[1]
    assert len(messages.requests) == 1

    answer = [e for e in bot.events if e[0] == "answer"]
    assert answer[0][1].startswith("Marcada como enviada")


def test_skip_button_and_errors(db_session, world):
    result = suggestions(db_session, world, count=1)
    request = result.new[0]
    handlers = build_handlers(factory(db_session))
    bot = FakeBot()

    outcome = handle_update(
        callback(f"{CONNECTION_SKIP_PREFIX}{request.id}"), chat_id=CHAT, bot=bot, generate=None, generated={}, hunter=handlers
    )
    db_session.expire_all()
    row = db_session.get(ConnectionRequest, request.id)
    assert outcome == "connection" and row.status == "SKIPPED" and row.skip_until is not None

    unknown = handle_update(
        callback(f"{CONNECTION_SENT_PREFIX}{uuid4()}"), chat_id=CHAT, bot=bot, generate=None, generated={}, hunter=handlers
    )
    assert unknown == "connection" and bot.events[-1] == ("answer", "Connection request not found.")


def test_replying_with_a_post_regenerates_that_persons_note(db_session, world):
    result = suggestions(db_session, world)
    send_connections(db_session, FakeProvider(), result.today, now=MONDAY, day_label="d")
    db_session.commit()
    target = db_session.scalars(select(ConnectionRequest).where(ConnectionRequest.telegram_message_id == "102")).one()
    *_, cv_dir, style = world
    client, messages = scripted_client("Hola, tu post sobre Java en Acme Pay me gustó; yo trabajo con Java y Kafka.")
    handlers = build_handlers(factory(db_session), client=client, cv_dir=cv_dir, style_guide_path=style)
    bot = FakeBot()

    outcome = handle_update(reply("Hoy hablamos de Java.", 102), chat_id=CHAT, bot=bot, generate=None, generated={}, hunter=handlers)

    assert outcome == "regenerated"
    db_session.expire_all()
    target = db_session.get(ConnectionRequest, target.id)
    assert target.grounding_post == "Hoy hablamos de Java." and "post" in target.note
    assert bot.events[-1][2] == 55 and "Nota regenerada" in bot.events[-1][1]
    assert "Hoy hablamos de Java." in messages.requests[0]["messages"][0]["content"][0]["text"]


def test_messages_that_are_not_replies_to_our_messages_or_from_other_chats_are_ignored(db_session, world):
    result = suggestions(db_session, world)
    send_connections(db_session, FakeProvider(), result.today, now=MONDAY, day_label="d")
    db_session.commit()
    client, messages = scripted_client("unused")
    handlers = build_handlers(factory(db_session), client=client)
    bot = FakeBot()

    for update in (
        reply("post", 102, chat=999),
        reply("post", 4040),  # replying to some other message
        {"update_id": 3, "message": {"chat": {"id": 4242}, "message_id": 1, "text": "hello"}},
        reply("   ", 102),
    ):
        assert handle_update(update, chat_id=CHAT, bot=bot, generate=None, generated={}, hunter=handlers) == "ignored"
    assert bot.events == [] and messages.requests == []


def test_hunter_buttons_without_handlers_are_answered_politely(db_session):
    bot = FakeBot()

    outcome = handle_update(
        callback(f"{HUNTER_DRAFT_PREFIX}{uuid4()}"), chat_id=CHAT, bot=bot, generate=None, generated={}, hunter=None
    )

    assert outcome == "ignored" and bot.events == [("answer", "Company Hunter no disponible")]


def test_format_drafts_names_the_contact_and_says_nothing_was_sent(db_session, world, tmp_path):
    company, *_rest, cv_dir, style = world
    from ai_job_hunter.company_hunter.service import draft_for_company

    outcome = draft_for_company(
        db_session, company.id, client=scripted_client(drafts_json())[0], language="es", cv_dir=cv_dir, style_guide_path=style
    )

    text = format_drafts(outcome)
    assert "Jane <Doe> — Engineering Manager" in text and "https://acme.example.test/team" in text
    assert "no se ha enviado nada" in text
