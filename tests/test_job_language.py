from ai_job_hunter.services.job_language import required_foreign_language, written_language


def test_required_languages_are_found_and_optional_or_english_ones_are_not():
    assert required_foreign_language("Fluent German is required") == "german"
    assert required_foreign_language("We need proficiency in Dutch and English") == "dutch"
    assert required_foreign_language("Excellent command of French (C1)") == "french"
    assert required_foreign_language("Native-level Swedish speaker") == "swedish"
    assert required_foreign_language("German is a plus") is None
    assert required_foreign_language("You speak German or Dutch, nice to have") is None
    assert required_foreign_language("Strong communication skills in English") is None
    assert required_foreign_language(None) is None


def test_the_language_a_posting_is_written_in():
    english = (
        "We are looking for a developer for our team in Berlin. You will work with Java and Spring and build the "
        "platform with us. The team is international and we offer you flexible hours with the option to work from "
        "home. You have experience and enjoy working in a team and building software with our people."
    )
    dutch = (
        "Wij zijn op zoek naar een developer voor ons team in Eindhoven. Je werkt met Java en Spring en ontwikkelt "
        "met ons het platform. Het team is internationaal en wij bieden je een flexibele werktijd met de mogelijkheid "
        "om thuis te werken. Je hebt ervaring en ook plezier in het werk van een team."
    )
    spanish = (
        "Buscamos un desarrollador para nuestro equipo en Madrid. Trabajarás con Java y Spring y construirás la "
        "plataforma con nosotros. El equipo es internacional y ofrecemos horario flexible con la posibilidad de "
        "trabajar desde casa. Tienes experiencia y disfrutas del trabajo en equipo."
    )
    assert written_language(dutch) == "dutch"
    assert written_language(english) is None and written_language(spanish) is None
    assert written_language("Too short to tell") is None
