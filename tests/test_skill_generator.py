# tests/test_skill_generator.py
import pytest
from pathlib import Path
from claudeclaw.skills.generator import SkillGenerator, WizardOutput
from claudeclaw.skills.loader import load_skill


@pytest.fixture
def generator(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    from claudeclaw.config.settings import get_settings
    get_settings.cache_clear()
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True)
    return SkillGenerator(skills_dir=skills_dir)


@pytest.fixture
def basic_wizard_output():
    return WizardOutput(
        task_description="Issue monthly invoices from the ERP and email them to clients",
        systems=["erp", "gmail"],
        credentials=["erp-invoices-erp-user", "erp-invoices-erp-token", "erp-invoices-gmail-token"],
        trigger="cron",
        schedule="0 0 28 * *",
        autonomy="autonomous",
    )


def test_generates_valid_md_file(generator, basic_wizard_output):
    path = generator.generate(basic_wizard_output)
    assert path.exists()
    assert path.suffix == ".md"


def test_generated_skill_has_valid_frontmatter(generator, basic_wizard_output):
    path = generator.generate(basic_wizard_output)
    skill = load_skill(path)
    assert skill.trigger == "cron"
    assert skill.schedule == "0 0 28 * *"
    assert skill.autonomy == "autonomous"
    assert "erp-invoices-erp-user" in skill.credentials


def test_generated_skill_name_is_kebab_case(generator, basic_wizard_output):
    path = generator.generate(basic_wizard_output)
    skill = load_skill(path)
    assert " " not in skill.name
    assert skill.name == skill.name.lower()


def test_deduplicates_slug_if_file_exists(generator, basic_wizard_output, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    from claudeclaw.config.settings import get_settings
    get_settings.cache_clear()
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    gen = SkillGenerator(skills_dir=skills_dir)

    path1 = gen.generate(basic_wizard_output)
    path2 = gen.generate(basic_wizard_output)
    assert path1 != path2
    assert path1.exists()
    assert path2.exists()


def test_on_demand_skill_has_no_schedule(generator):
    output = WizardOutput(
        task_description="Answer customer questions",
        systems=[],
        credentials=[],
        trigger="on-demand",
        schedule=None,
        autonomy="ask",
    )
    path = generator.generate(output)
    skill = load_skill(path)
    assert skill.trigger == "on-demand"
    assert skill.schedule is None


def test_webhook_skill_has_trigger_id(generator):
    output = WizardOutput(
        task_description="Process new CRM lead",
        systems=["crm"],
        credentials=["crm-lead-crm-token"],
        trigger="webhook",
        schedule=None,
        autonomy="notify",
    )
    path = generator.generate(output)
    skill = load_skill(path)
    assert skill.trigger == "webhook"
    assert skill.trigger_id is not None
