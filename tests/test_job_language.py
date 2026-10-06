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


def test_postings_in_portuguese_italian_or_polish_are_foreign_and_spanish_or_english_never_are():
    portuguese = (
        "Estamos à procura de um programador para a nossa equipa em Lisboa. Vais trabalhar com Java e Spring e "
        "desenvolver a plataforma connosco. Não é necessária experiência anterior, mas gostamos de quem está "
        "motivado e também de quem conhece bem o desenvolvimento de software e o trabalho em equipa na empresa. "
        "A nossa empresa oferece um horário flexível e a possibilidade de trabalhar em casa."
    )
    italian = (
        "Cerchiamo uno sviluppatore per il nostro team a Milano. Lavorerai con Java e Spring e svilupperai la "
        "piattaforma con noi. Non è necessaria esperienza precedente, ma cerchiamo persone che sono motivate e "
        "che conoscono anche il lavoro in squadra. La nostra azienda offre un orario flessibile e più benefici "
        "per il lavoro da casa nella sede."
    )
    spanish = (
        "Buscamos un desarrollador para nuestro equipo en Madrid. Trabajarás con Java y Spring y construirás la "
        "plataforma con nosotros. No es necesaria experiencia previa, pero buscamos personas motivadas que "
        "conozcan el desarrollo de software y el trabajo en equipo. Nuestra empresa ofrece horario flexible y "
        "la posibilidad de trabajar desde casa con un salario acorde a la experiencia."
    )

    assert written_language(portuguese) == "portuguese"
    assert written_language(italian) == "italian"
    assert written_language(spanish) is None
    assert written_language(portuguese, spoken=frozenset({"portuguese"})) is None
