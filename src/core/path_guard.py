"""
path_guard — Validação de caminhos de arquivo para operações seguras.

Fornece validate_path() como ponto central de sanitização para o executor
e quaisquer outros consumidores que precisem rejeitar caminhos perigosos
antes de tocar no sistema de arquivos.

Regras aplicadas:
  1. O caminho não pode ser vazio.
  2. O caminho deve ser absoluto — caminhos relativos são rejeitados.
  3. Após resolução canônica, o caminho não pode apontar para diretórios
     protegidos do Windows (System32, Program Files, ProgramData, etc.).
  4. O nome do arquivo não pode ser um arquivo de sistema crítico.

Uso::

    from src.core.path_guard import validate_path

    ok, err = validate_path("C:/Users/joao/Videos/filme.mkv")
    # ok=True, err=""

    ok, err = validate_path("../../../Windows/System32/calc.exe")
    # ok=False, err="Caminhos relativos não são permitidos..."
"""

from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# Constantes de proteção
# ---------------------------------------------------------------------------

#: Prefixos de diretórios do Windows que nunca devem ser modificados.
#: Usados em comparação case-insensitive (upper).
PROTECTED_PATH_PREFIXES: tuple[str, ...] = (
    "C:\\WINDOWS",
    "C:\\PROGRAM FILES",
    "C:\\PROGRAM FILES (X86)",
    "C:\\PROGRAMDATA",
    "C:\\SYSTEM VOLUME INFORMATION",
    "C:\\$RECYCLE.BIN",
    "C:\\RECOVERY",
    "C:\\BOOT",
)

#: Nomes de arquivos de sistema críticos (case-insensitive).
PROTECTED_FILENAMES: frozenset[str] = frozenset({
    "pagefile.sys",
    "swapfile.sys",
    "hiberfil.sys",
    "ntldr",
    "bootmgr",
    "ntdetect.com",
    "boot.ini",
    "io.sys",
    "msdos.sys",
})


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def validate_path(path: str) -> tuple[bool, str]:
    """
    Valida que um caminho é seguro para operações de arquivo.

    Parameters
    ----------
    path : str
        Caminho a validar (pode ser absoluto ou relativo).

    Returns
    -------
    tuple[bool, str]
        ``(True, "")`` se o caminho for seguro.
        ``(False, mensagem_de_erro)`` se for rejeitado.

    Examples
    --------
    >>> ok, err = validate_path("C:/Users/joao/Videos/filme.mkv")
    >>> assert ok and err == ""

    >>> ok, err = validate_path("../../../Windows/calc.exe")
    >>> assert not ok and "relativo" in err
    """
    if not path or not path.strip():
        return False, "Caminho vazio não é permitido."

    p = Path(path)

    # Regra 1 — Rejeitar caminhos relativos
    if not p.is_absolute():
        return False, (
            f"Caminhos relativos não são permitidos: '{path}'. "
            "Forneça o caminho absoluto completo."
        )

    # Regra 2 — Resolver canonicamente (elimina symlinks e componentes '..')
    try:
        resolved = p.resolve()
    except (OSError, ValueError) as exc:
        return False, f"Caminho inválido ou inacessível: {exc}"

    resolved_upper = str(resolved).upper()

    # Regra 3 — Verificar diretórios protegidos
    for prefix in PROTECTED_PATH_PREFIXES:
        if resolved_upper.startswith(prefix):
            return False, (
                f"Acesso a diretório de sistema protegido bloqueado: "
                f"'{resolved}' está dentro de '{prefix}'."
            )

    # Regra 4 — Verificar nomes de arquivo críticos
    if resolved.name.lower() in PROTECTED_FILENAMES:
        return False, (
            f"Arquivo de sistema crítico protegido: '{resolved.name}'. "
            "Esta operação não é permitida."
        )

    return True, ""


def assert_safe_path(path: str) -> None:
    """
    Valida o caminho e lança ValueError se inválido.

    Conveniente para uso em funções que preferem exceção a retorno de tupla.

    Raises
    ------
    ValueError
        Se o caminho for rejeitado por validate_path.
    """
    ok, err = validate_path(path)
    if not ok:
        raise ValueError(err)
