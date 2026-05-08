"""
Testes unitários do módulo src.core.skills_loader.

Cobre:
  - _parse_frontmatter()    — com e sem frontmatter, múltiplos campos
  - _name_from_filename()   — prefixos numéricos, underscores
  - load_skills()           — diretório vazio, inexistente, múltiplos arquivos,
                              ordenação, erro de leitura, arquivo sem frontmatter
  - get_skill_by_name()     — encontrado, não encontrado, case-sensitive
  - Skill dataclass         — campos imutáveis (frozen=True)

Estratégia:
  - tmp_path do pytest para criar estruturas de diretório temporárias
  - Nenhuma dependência de PyQt6 ou banco de dados
"""

from __future__ import annotations

import pytest
from pathlib import Path

from src.core.skills_loader import (
    Skill,
    _name_from_filename,
    _parse_frontmatter,
    get_skill_by_name,
    load_skills,
)


# ─────────────────────────────────────────────────────────────────────────────
# _parse_frontmatter
# ─────────────────────────────────────────────────────────────────────────────

class TestParseFrontmatter:
    def test_returns_empty_meta_and_full_text_when_no_frontmatter(self):
        text = "# Hello\nSome content."
        meta, content = _parse_frontmatter(text)
        assert meta == {}
        assert content == text

    def test_extracts_name_and_description(self):
        text = "---\nname: Limpeza\ndescription: Limpa arquivos\n---\nContent here."
        meta, content = _parse_frontmatter(text)
        assert meta["name"] == "Limpeza"
        assert meta["description"] == "Limpa arquivos"

    def test_content_does_not_contain_frontmatter_block(self):
        text = "---\nname: Test\n---\n# Body\nLine2."
        _, content = _parse_frontmatter(text)
        assert "---" not in content
        assert "name: Test" not in content
        assert "# Body" in content

    def test_handles_value_with_colon(self):
        text = "---\nname: Skill: Avançada\n---\nBody."
        meta, _ = _parse_frontmatter(text)
        # Partição na primeira ocorrência de ':'
        assert meta["name"] == "Skill: Avançada"

    def test_ignores_lines_without_colon_in_frontmatter(self):
        text = "---\nname: Valid\nnot-a-kv-pair\n---\nBody."
        meta, _ = _parse_frontmatter(text)
        assert "not-a-kv-pair" not in meta
        assert meta["name"] == "Valid"

    def test_incomplete_frontmatter_not_parsed(self):
        text = "---\nname: Orphan\nBody without closing fence."
        meta, content = _parse_frontmatter(text)
        assert meta == {}
        assert content == text

    def test_strips_whitespace_from_keys_and_values(self):
        text = "---\n  name  :  My Skill  \n---\nBody."
        meta, _ = _parse_frontmatter(text)
        assert meta["name"] == "My Skill"


# ─────────────────────────────────────────────────────────────────────────────
# _name_from_filename
# ─────────────────────────────────────────────────────────────────────────────

class TestNameFromFilename:
    def test_removes_numeric_prefix_with_underscore(self):
        assert _name_from_filename("01_limpeza_midia") == "Limpeza Midia"

    def test_removes_numeric_prefix_with_dash(self):
        assert _name_from_filename("02-clean-ssd") == "Clean Ssd"

    def test_no_prefix_uses_full_name(self):
        assert _name_from_filename("limpeza") == "Limpeza"

    def test_underscores_become_spaces(self):
        assert _name_from_filename("my_skill_name") == "My Skill Name"

    def test_capitalizes_each_word(self):
        assert _name_from_filename("03_duplicatas_rapidas") == "Duplicatas Rapidas"


# ─────────────────────────────────────────────────────────────────────────────
# load_skills
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadSkills:
    def test_returns_empty_list_for_nonexistent_dir(self, tmp_path):
        result = load_skills(tmp_path / "nao_existe")
        assert result == []

    def test_returns_empty_list_for_empty_directory(self, tmp_path):
        result = load_skills(tmp_path)
        assert result == []

    def test_ignores_non_md_files(self, tmp_path):
        (tmp_path / "readme.txt").write_text("plain text", encoding="utf-8")
        (tmp_path / "config.json").write_text("{}", encoding="utf-8")
        assert load_skills(tmp_path) == []

    def test_loads_single_skill_with_frontmatter(self, tmp_path):
        (tmp_path / "skill_a.md").write_text(
            "---\nname: Skill A\ndescription: Desc A\n---\nContent A.",
            encoding="utf-8",
        )
        skills = load_skills(tmp_path)
        assert len(skills) == 1
        assert skills[0].name == "Skill A"
        assert skills[0].description == "Desc A"
        assert skills[0].content == "Content A."
        assert skills[0].filename == "skill_a"

    def test_skill_without_frontmatter_uses_filename_as_name(self, tmp_path):
        (tmp_path / "01_clean_downloads.md").write_text(
            "# Instructions\nDo this.", encoding="utf-8"
        )
        skills = load_skills(tmp_path)
        assert len(skills) == 1
        assert skills[0].name == "Clean Downloads"
        assert skills[0].content == "# Instructions\nDo this."
        assert skills[0].description == ""

    def test_loads_multiple_skills_sorted_by_name(self, tmp_path):
        (tmp_path / "zzz.md").write_text(
            "---\nname: Zebra Skill\n---\nZ content.", encoding="utf-8"
        )
        (tmp_path / "aaa.md").write_text(
            "---\nname: Alpha Skill\n---\nA content.", encoding="utf-8"
        )
        (tmp_path / "mmm.md").write_text(
            "---\nname: Middle Skill\n---\nM content.", encoding="utf-8"
        )
        skills = load_skills(tmp_path)
        assert [s.name for s in skills] == ["Alpha Skill", "Middle Skill", "Zebra Skill"]

    def test_skips_unreadable_file_silently(self, tmp_path):
        # Criar arquivo válido
        (tmp_path / "valid.md").write_text(
            "---\nname: Valid\n---\nOK.", encoding="utf-8"
        )
        # Criar arquivo com bytes inválidos UTF-8
        invalid = tmp_path / "broken.md"
        invalid.write_bytes(b"---\nname: \xff\xfe Invalid\n---\nContent.")
        skills = load_skills(tmp_path)
        # Pelo menos o arquivo válido deve ser carregado
        names = [s.name for s in skills]
        assert "Valid" in names

    def test_content_stripped_of_leading_trailing_whitespace(self, tmp_path):
        (tmp_path / "spaced.md").write_text(
            "---\nname: Spaced\n---\n\n\n# Title\nBody.\n\n",
            encoding="utf-8",
        )
        skills = load_skills(tmp_path)
        assert not skills[0].content.startswith("\n")
        assert not skills[0].content.endswith("\n")

    def test_skill_is_frozen_dataclass(self, tmp_path):
        (tmp_path / "frozen.md").write_text(
            "---\nname: Frozen\n---\nContent.", encoding="utf-8"
        )
        skill = load_skills(tmp_path)[0]
        with pytest.raises((AttributeError, TypeError)):
            skill.name = "Modified"  # type: ignore[misc]

    def test_loads_real_skills_directory(self):
        """Verifica que o diretório skills/ do projeto tem pelo menos 4 arquivos."""
        skills = load_skills()  # usa DEFAULT_SKILLS_DIR
        assert len(skills) >= 4, (
            f"Esperado ≥4 skills na pasta skills/, encontrado {len(skills)}"
        )

    def test_real_skills_have_name_and_content(self):
        """Cada skill real deve ter nome não vazio e conteúdo não vazio."""
        for skill in load_skills():
            assert skill.name, f"Skill sem nome: {skill.filename}"
            assert skill.content, f"Skill sem conteúdo: {skill.filename}"


# ─────────────────────────────────────────────────────────────────────────────
# get_skill_by_name
# ─────────────────────────────────────────────────────────────────────────────

class TestGetSkillByName:
    def _setup_dir(self, tmp_path: Path) -> Path:
        (tmp_path / "alpha.md").write_text(
            "---\nname: Alpha\ndescription: First\n---\nAlpha content.",
            encoding="utf-8",
        )
        (tmp_path / "beta.md").write_text(
            "---\nname: Beta\ndescription: Second\n---\nBeta content.",
            encoding="utf-8",
        )
        return tmp_path

    def test_returns_skill_when_name_matches(self, tmp_path):
        self._setup_dir(tmp_path)
        skill = get_skill_by_name("Alpha", skills_dir=tmp_path)
        assert skill is not None
        assert skill.name == "Alpha"
        assert skill.content == "Alpha content."

    def test_returns_none_when_name_not_found(self, tmp_path):
        self._setup_dir(tmp_path)
        assert get_skill_by_name("Nonexistent", skills_dir=tmp_path) is None

    def test_is_case_sensitive(self, tmp_path):
        self._setup_dir(tmp_path)
        assert get_skill_by_name("alpha", skills_dir=tmp_path) is None
        assert get_skill_by_name("ALPHA", skills_dir=tmp_path) is None
        assert get_skill_by_name("Alpha", skills_dir=tmp_path) is not None

    def test_returns_none_for_empty_directory(self, tmp_path):
        assert get_skill_by_name("Any", skills_dir=tmp_path) is None

    def test_returns_correct_skill_among_many(self, tmp_path):
        self._setup_dir(tmp_path)
        skill = get_skill_by_name("Beta", skills_dir=tmp_path)
        assert skill is not None
        assert skill.description == "Second"
        assert skill.filename == "beta"

    def test_real_skills_findable_by_name(self):
        """Cada skill real deve ser encontrável pelo próprio nome."""
        for skill in load_skills():
            found = get_skill_by_name(skill.name)
            assert found is not None, f"Skill '{skill.name}' não encontrável por nome"
            assert found.filename == skill.filename
