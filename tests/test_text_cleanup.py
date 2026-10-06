from ai_job_hunter.services.text_cleanup import clean_letter_text


def test_letters_get_plain_punctuation_and_no_invisible_characters():
    dirty = "I’m Javier​ — a “backend” developer. Spring… 2025–2026 and Java – REST.﻿"

    assert clean_letter_text(dirty) == "I'm Javier, a \"backend\" developer. Spring... 2025-2026 and Java, REST."


def test_accents_and_line_breaks_are_kept():
    text = "Hola, soy Javier.\n\nEstudié Ingeniería Informática en la Carlos III."

    assert clean_letter_text(text) == text
    assert clean_letter_text("Gracias —.") == "Gracias."
