from test_onboarding import CV_DRAFT, NOW  # noqa: F401
from test_onboarding import new_user

from ai_job_hunter.models.user import UserProfile
from ai_job_hunter.services import profile_edit
from ai_job_hunter.services.onboarding import build_config, handle_command
from ai_job_hunter.services.users import load_profile, save_profile


def active_person(db_session):
    _, user = new_user(db_session)
    user.status = "ACTIVE"
    save_profile(db_session, user, build_config({**CV_DRAFT, "sector": "finance", "role": "Contable", "locations": ["Madrid"]}))
    return user


def prefs(db_session, user):
    return load_profile(db_session, user).preferences


def test_profile_shows_the_answers_with_a_button_for_each_and_text_answers_are_read_after_asking(db_session) -> None:
    user = active_person(db_session)
    menu = handle_command(db_session, user, "/profile")[0]
    assert "Puesto: Contable" in menu.text and "Lugares: Madrid" in menu.text
    assert sorted(b.data for row in menu.buttons for b in row) == sorted(f"pf:edit:{k}" for k in profile_edit.LABELS)
    assert handle_command(db_session, user, "/perfil")[0].text == menu.text  # Spanish alias

    ask = profile_edit.press(db_session, user, "pf:edit:role")[0]
    assert "¿Qué puesto buscas?" in ask.text and profile_edit.is_editing(user)
    done = profile_edit.text(db_session, user, "Analista financiero")
    assert done[0].text == "Hecho." and "Puesto: Analista financiero" in done[1].text
    assert prefs(db_session, user).preferred_roles == ["Analista financiero"] and not profile_edit.is_editing(user)

    profile_edit.press(db_session, user, "pf:edit:locations")
    profile_edit.text(db_session, user, "Barcelona; Valencia")
    assert prefs(db_session, user).acceptable_locations == ["Barcelona", "Valencia"]


def test_salary_can_be_changed_cleared_and_a_bad_figure_asks_again(db_session) -> None:
    user = active_person(db_session)
    profile_edit.press(db_session, user, "pf:edit:salary")
    assert "No he entendido" in profile_edit.text(db_session, user, "mucho")[0].text and profile_edit.is_editing(user)
    profile_edit.text(db_session, user, "35k €")
    assert prefs(db_session, user).minimum_salary == 35000
    profile_edit.press(db_session, user, "pf:edit:salary")
    profile_edit.text(db_session, user, "saltar")
    assert prefs(db_session, user).minimum_salary is None


def test_button_choices_change_only_their_own_field_and_keep_the_cv_summary(db_session) -> None:
    user = active_person(db_session)
    row = db_session.query(UserProfile).filter_by(user_id=user.id).one()
    row.cv_text = "Contable en Acme."
    years = load_profile(db_session, user).profile.years_of_experience

    profile_edit.press(db_session, user, "pf:set:mode:remote")
    profile_edit.press(db_session, user, "pf:set:nosalary:no")
    profile_edit.press(db_session, user, "pf:set:reloc:yes")
    profile_edit.press(db_session, user, "pf:set:contract:no")
    changed = prefs(db_session, user)
    assert changed.remote_preference.value == "REMOTE_ONLY" and changed.accept_offers_without_salary is False
    assert changed.relocation_willingness is True
    assert "INTERNSHIP" not in [item.value for item in changed.acceptable_employment_types] and changed.acceptable_employment_types

    profile_edit.press(db_session, user, "pf:set:contract:yes")
    assert prefs(db_session, user).acceptable_employment_types == []  # every type again
    assert row.cv_text == "Contable en Acme." and load_profile(db_session, user).profile.years_of_experience == years
    assert "No he podido" in profile_edit.press(db_session, user, "pf:set:mode:nonsense")[0].text
