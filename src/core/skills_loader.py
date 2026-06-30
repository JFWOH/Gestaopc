"""
Carregador de Skills RAG — perfis de limpeza selecionáveis sem alterar código.

Uma "Skill" é um arquivo .md na pasta ``skills/`` (raiz do projeto) com
frontmatter YAML opcional. Quando selecionada na interface, o conteúdo da
skill é injetado no system context do Assistente IA, direcionando o modelo
para um modo de limpeza/otimização específico.

Formato de um arquivo .md de skill::

    ---
    name: Limpeza de Mídia
    description: Foca em arquivos de vídeo e áudio duplicados ou mal alocados.
    ---

    # Instruções para Limpeza de Mídia

    Ao analisar o sistema, priorize...

O bloco ``---`` é opcional. Se ausente, o nome é gerado a partir do nome do
arquivo (ex: ``01_limpeza_midia.md`` → ``"Limpeza Midia"``).

Uso::

    from src.core.skills_loader import load_skills, get_skill_by_name

    skills = load_skills()               # Carrega da pasta skills/ padrão
    skill  = get_skill_by_name("Limpeza de Mídia")
    print(skill.content)                 # Instruções Markdown sem frontmatter
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Localização padrão da pasta de skills (raiz do projeto)
DEFAULT_SKILLS_DIR: Path = (
    Path(__file__).resolve().parent.parent.parent / "skills"
)


# ─────────────────────────────────────────────────────────────────────────────
# Modelo de dados
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Skill:
    """Representa um perfil de limpeza/otimização carregado de um arquivo .md."""

    name: str
    """Nome legível do perfil (frontmatter ou gerado do nome do arquivo)."""

    description: str
    """Descrição curta (frontmatter ou string vazia)."""

    content: str
    """Conteúdo Markdown sem o bloco de frontmatter — injetado no system prompt."""

    filename: str
    """Nome do arquivo sem extensão (ex: '01_limpeza_midia')."""


# ─────────────────────────────────────────────────────────────────────────────
# Parser de frontmatter
# ─────────────────────────────────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """
    Extrai frontmatter YAML simples (``chave: valor``) de um texto Markdown.

    Args:
        text: Conteúdo completo do arquivo .md.

    Returns:
        Tupla ``(meta_dict, content_without_frontmatter)``.
        Se não houver frontmatter, retorna ``({}, text)``.
    """
    meta: dict[str, str] = {}
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return meta, text

    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()

    return meta, text[match.end():]


def _name_from_filename(stem: str) -> str:
    """Gera nome legível a partir do nome do arquivo (sem extensão).

    Ex: ``01_limpeza_de_midia`` → ``"Limpeza De Midia"``
    """
    # Remove prefixo numérico (ex: '01_', '02-')
    cleaned = re.sub(r"^\d+[_\-]", "", stem)
    return cleaned.replace("_", " ").replace("-", " ").title()


# ─────────────────────────────────────────────────────────────────────────────
# Funções públicas
# ─────────────────────────────────────────────────────────────────────────────

def load_skills(skills_dir: Path | str | None = None) -> list[Skill]:
    """
    Carrega todos os arquivos ``.md`` da pasta de skills como objetos :class:`Skill`.

    Arquivos com erros de leitura são silenciosamente ignorados.

    Args:
        skills_dir: Diretório de skills. Padrão: ``skills/`` na raiz do projeto.

    Returns:
        Lista de :class:`Skill` ordenada pelo campo ``name`` (alfabético).
    """
    dir_path = Path(skills_dir) if skills_dir is not None else DEFAULT_SKILLS_DIR

    if not dir_path.is_dir():
        return []

    skills: list[Skill] = []
    for md_file in dir_path.glob("*.md"):
        try:
            text = md_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        meta, body = _parse_frontmatter(text)
        name = meta.get("name") or _name_from_filename(md_file.stem)
        description = meta.get("description", "")

        skills.append(
            Skill(
                name=name,
                description=description,
                content=body.strip(),
                filename=md_file.stem,
            )
        )

    return sorted(skills, key=lambda s: s.name)


def get_skill_by_name(
    name: str, skills_dir: Path | str | None = None
) -> Skill | None:
    """
    Retorna a :class:`Skill` com o nome exato especificado.

    Args:
        name: Nome da skill (case-sensitive, igual ao campo ``name`` do frontmatter).
        skills_dir: Diretório de skills. Padrão: ``skills/`` na raiz do projeto.

    Returns:
        :class:`Skill` correspondente ou ``None`` se não encontrada.
    """
    for skill in load_skills(skills_dir):
        if skill.name == name:
            return skill
    return None
