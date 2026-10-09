from pathlib import Path

import pytest

from app.services import prompts


def test_load_prompt_reads_the_file_from_app_prompts() -> None:
    text = prompts.load_prompt("rag_system")

    assert "<document" in text
    assert text == (prompts.PROMPTS_DIR / "rag_system.md").read_text(encoding="utf-8")


def test_load_prompt_reads_at_call_time_not_import_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "probe.md").write_text("first", encoding="utf-8")
    monkeypatch.setattr(prompts, "PROMPTS_DIR", tmp_path)
    prompts.load_prompt.cache_clear()

    assert prompts.load_prompt("probe") == "first"


@pytest.mark.parametrize("name", ["../secrets", "rag_system.md", "a/b", ""])
def test_load_prompt_rejects_names_that_are_not_plain_prompt_names(name: str) -> None:
    with pytest.raises(ValueError):
        prompts.load_prompt(name)


def test_the_user_template_has_one_documents_and_one_question_slot() -> None:
    template = prompts.load_prompt("rag_user")

    assert template.count("{{documents}}") == 1
    assert template.count("{{question}}") == 1
    assert template.index("{{documents}}") < template.index("{{question}}")
