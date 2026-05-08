"""
AI Toolbelt — Camada centralizada de ferramentas para agentes de IA.

Expõe 12 tools consumíveis pelo Servidor MCP e pelo Assistente Ollama.
Zero dependências de PyQt6 — importável em qualquer contexto (CLI, testes, servidores).

Design:
  • Todas as funções retornam dict | list[dict] — sempre JSON-serializável.
  • Tools executivas exigem token one-shot (via request_confirmation) e
    verificam: rate-limit → path protegido → token → execução → auditoria.
  • O parâmetro ``ai_source`` indica quem disparou a ação para auditoria:
    'ai:ollama' (padrão) ou 'ai:mcp' (passado pelo servidor MCP).

Uso::

    from src.core.ai_toolbelt import list_partitions, request_confirmation, move_file

    parts = list_partitions()

    tok = request_confirmation("move_file", {"source_path": "C:/a.mkv", "target_path": "D:/a.mkv"})
    result = move_file("C:/a.mkv", "D:/a.mkv", tok["token"])
"""

from __future__ import annotations

import logging
import os
import secrets
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.core.scanner import StorageScanner
from src.core.storage_db import StorageManagerDB, get_default_db_path

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Segurança — caminhos e nomes de arquivo protegidos
# ─────────────────────────────────────────────────────────────────────────────

PROTECTED_PATH_PREFIXES: list[str] = [
    "C:\\WINDOWS",
    "C:\\PROGRAM FILES",
    "C:\\PROGRAM FILES (X86)",
    "C:\\PROGRAMDATA",
    "C:\\SYSTEM VOLUME INFORMATION",
    "C:\\$RECYCLE.BIN",
]

PROTECTED_FILENAMES: set[str] = {
    "pagefile.sys",
    "swapfile.sys",
    "hiberfil.sys",
    "ntldr",
    "bootmgr",
    "ntdetect.com",
}

VALID_DISK_ROLES: set[str] = {"primary", "media", "backup", "external", "none"}

EXECUTIVE_ACTIONS: set[str] = {
    "move_to_trash",
    "move_file",
    "apply_suggestion",
    "undo_last_operation",
    "set_disk_role",
}

# Limites de execução
_MAX_EXEC_PER_MINUTE: int = 3
_TOKEN_TTL_SECONDS: int = 60


# ─────────────────────────────────────────────────────────────────────────────
# Token store (in-memory, escopo por processo)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class _ConfirmationToken:
    token: str
    action: str
    args: dict
    expires_at: float


_token_store: dict[str, _ConfirmationToken] = {}


def _clean_expired_tokens() -> None:
    now = time.time()
    expired = [t for t, v in _token_store.items() if v.expires_at <= now]
    for t in expired:
        del _token_store[t]


# ─────────────────────────────────────────────────────────────────────────────
# Rate limiter (in-memory, escopo por processo)
# ─────────────────────────────────────────────────────────────────────────────

_exec_timestamps: list[float] = []


def _check_rate_limit() -> dict | None:
    """Verifica rate limit. Retorna dict de erro se excedido, None se OK."""
    global _exec_timestamps
    now = time.time()
    _exec_timestamps = [t for t in _exec_timestamps if now - t < 60]
    if len(_exec_timestamps) >= _MAX_EXEC_PER_MINUTE:
        return {
            "error": "RATE_LIMIT_EXCEEDED",
            "message": (
                f"Limite de {_MAX_EXEC_PER_MINUTE} ações executivas por minuto atingido. "
                "Aguarde antes de continuar."
            ),
        }
    return None


def _record_exec() -> None:
    _exec_timestamps.append(time.time())


# ─────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────────────────

def _human_size(size_bytes: int) -> str:
    """Converte bytes para string legível (B/KB/MB/GB)."""
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / (1024 ** 3):.1f} GB"
    if size_bytes >= 1024 ** 2:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def _is_protected(path: str) -> bool:
    """Retorna True se o caminho ou nome do arquivo é protegido pelo SO."""
    p = Path(path)
    if p.name.lower() in PROTECTED_FILENAMES:
        return True
    path_upper = str(p.resolve()).upper()
    return any(path_upper.startswith(prefix) for prefix in PROTECTED_PATH_PREFIXES)


def _validate_token(token: str, action: str) -> dict | None:
    """
    Valida token one-shot para uma ação executiva.

    Retorna None se válido e consume o token.
    Retorna dict de erro se inválido, expirado ou incompatível.
    """
    ct = _token_store.get(token)
    if ct is None:
        _clean_expired_tokens()  # housekeeping passivo
        return {
            "error": "INVALID_TOKEN",
            "message": "Token inválido ou expirado. Solicite um novo via request_confirmation.",
        }
    if ct.expires_at <= time.time():
        del _token_store[token]
        _clean_expired_tokens()
        return {
            "error": "TOKEN_EXPIRED",
            "message": "Token expirado. Solicite um novo via request_confirmation.",
        }
    if ct.action != action:
        return {
            "error": "TOKEN_MISMATCH",
            "message": f"Token emitido para '{ct.action}', não para '{action}'.",
        }
    del _token_store[token]  # one-shot: consumir após validação
    return None


def _fmt_ts(ts: float | None) -> str | None:
    """Formata timestamp Unix para ISO 8601, ou None."""
    if ts is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


def _open_db() -> StorageManagerDB:
    """Retorna instância de DB para uso como context manager."""
    return StorageManagerDB(get_default_db_path())


# ─────────────────────────────────────────────────────────────────────────────
# Funções auxiliares para reset em testes
# ─────────────────────────────────────────────────────────────────────────────

def _reset_rate_limiter() -> None:
    """Limpa o histórico de rate limiting. Apenas para uso em testes."""
    global _exec_timestamps
    _exec_timestamps = []


def _reset_token_store() -> None:
    """Limpa todos os tokens. Apenas para uso em testes."""
    _token_store.clear()


# ─────────────────────────────────────────────────────────────────────────────
# TOOLS DE LEITURA (read_only=True, requires_confirmation=False)
# ─────────────────────────────────────────────────────────────────────────────

def list_partitions() -> list[dict]:
    """
    Lista todas as partições do sistema com espaço, tipo de mídia e percentual de uso.

    Retorno: lista de dicts com keys: letter, fstype, media_type,
    total_gb, free_gb, used_pct.
    """
    try:
        scanner = StorageScanner()
        parts = scanner.list_partitions()
        return [
            {
                "letter": p.letter,
                "fstype": p.fstype,
                "media_type": p.media_type,
                "total_gb": round(p.total_gb, 1),
                "free_gb": round(p.free_gb, 1),
                "used_pct": round(p.percent_used, 1),
            }
            for p in parts
        ]
    except Exception as exc:
        logger.exception("Erro em list_partitions")
        return [{"error": "SCAN_ERROR", "message": str(exc)}]


def find_top_files(
    limit: int = 50,
    category: str | None = None,
    drive_letter: str | None = None,
) -> list[dict]:
    """
    Retorna os N maiores arquivos do índice persistido (último scan).

    Se o índice estiver vazio, retorna mensagem orientando executar varredura.

    Args:
        limit: Máximo de arquivos (1–100, padrão 50).
        category: Filtrar por categoria ('Vídeos', 'Imagens', 'Documentos',
                  'Executáveis', 'Compactados', 'Outros').
        drive_letter: Filtrar por disco ('C', 'D', 'C:', etc.).
    """
    limit = min(max(1, limit), 100)
    try:
        with _open_db() as db:
            rows = db.list_file_index(
                limit=limit,
                category=category,
                disk_letter=drive_letter,
            )
        if not rows:
            return [
                {
                    "error": "NO_DATA",
                    "message": (
                        "Nenhum arquivo no índice. "
                        "Execute uma varredura completa via interface gráfica primeiro."
                    ),
                }
            ]
        return [
            {
                "path": row["path"],
                "size_bytes": row["size_bytes"],
                "size_human": _human_size(row["size_bytes"]),
                "category": row["category"] or "Outros",
                "drive_letter": row["disk_letter"] or "",
                "last_modified": _fmt_ts(row["mtime"]),
            }
            for row in rows
        ]
    except Exception as exc:
        logger.exception("Erro em find_top_files")
        return [{"error": "DB_ERROR", "message": str(exc)}]


def find_top_folders(
    limit: int = 20,
    drive_letter: str | None = None,
) -> list[dict]:
    """
    Varre diretórios e retorna os N que mais consomem espaço.

    Realiza varredura ao vivo (pode levar alguns segundos).

    Args:
        limit: Máximo de pastas (1–50, padrão 20).
        drive_letter: Varrer apenas este disco ('C', 'D', 'C:\\', etc.).
                      Se omitido, varre todas as partições.
    """
    limit = min(max(1, limit), 50)
    try:
        scanner = StorageScanner()
        results: list[dict] = []

        def _entry_to_dict(d: Any, letter: str) -> dict:
            return {
                "path": d.path,
                "size_bytes": d.total_size_bytes,
                "size_human": _human_size(d.total_size_bytes),
                "file_count": d.file_count,
                "drive_letter": letter,
            }

        if drive_letter:
            letter = drive_letter.strip().upper().rstrip(":\\/")
            root = letter + ":\\"
            dirs = scanner.top_largest_dirs(root, n=limit)
            results = [_entry_to_dict(d, letter + ":") for d in dirs]
        else:
            parts = scanner.list_partitions()
            for p in parts:
                root = p.letter + "\\"
                dirs = scanner.top_largest_dirs(root, n=limit)
                results.extend(_entry_to_dict(d, p.letter) for d in dirs)
            results.sort(key=lambda x: x["size_bytes"], reverse=True)
            results = results[:limit]

        if not results:
            return [{"error": "NO_DATA", "message": "Nenhum diretório encontrado."}]
        return results
    except Exception as exc:
        logger.exception("Erro em find_top_folders")
        return [{"error": "SCAN_ERROR", "message": str(exc)}]


def find_duplicates(
    limit: int = 50,
    min_size_mb: float = 1.0,
) -> list[dict]:
    """
    Retorna grupos de arquivos duplicados detectados no índice persistido.

    Baseado em hashes SHA-256 armazenados no file_index. Se o índice estiver
    vazio ou sem hashes, orienta executar varredura completa.

    Args:
        limit: Máximo de grupos (1–200, padrão 50).
        min_size_mb: Ignorar duplicatas menores que este tamanho em MB.
    """
    limit = min(max(1, limit), 200)
    min_size_bytes = int(min_size_mb * 1024 * 1024)
    try:
        with _open_db() as db:
            groups = db.find_duplicates_from_index(
                limit=limit,
                min_size_bytes=min_size_bytes,
            )
        if not groups:
            return [
                {
                    "error": "NO_DATA",
                    "message": (
                        "Nenhuma duplicata encontrada no índice. "
                        "Execute uma varredura completa via interface gráfica primeiro."
                    ),
                }
            ]
        return [
            {
                "hash": g["hash"],
                "file_count": g["file_count"],
                "size_each_bytes": g["size_each_bytes"],
                "size_each_human": _human_size(g["size_each_bytes"]),
                "wasted_bytes": g["wasted_bytes"],
                "wasted_human": _human_size(g["wasted_bytes"]),
                "files": g["files"],
            }
            for g in groups
        ]
    except Exception as exc:
        logger.exception("Erro em find_duplicates")
        return [{"error": "DB_ERROR", "message": str(exc)}]


def list_suggestions(
    include_dismissed: bool = False,
    limit: int = 20,
) -> list[dict]:
    """
    Retorna sugestões geradas pelo SmartRulesEngine no último scan.

    Args:
        include_dismissed: Incluir sugestões já descartadas.
        limit: Máximo de sugestões (1–100, padrão 20).
    """
    limit = min(max(1, limit), 100)
    try:
        with _open_db() as db:
            rows = db.list_suggestions(include_dismissed=include_dismissed)
        return [
            {
                "id": row["id"],
                "rule_id": row["rule_id"],
                "rule_name": row["rule_name"],
                "file_path": row["file_path"],
                "action": row["action"],
                "detail": row["detail"],
                "target_disk": row["target_disk"] or "",
                "priority": row["priority"],
                "dismissed": bool(row["dismissed"]),
                "executed": bool(row["executed"]),
                "created_at": _fmt_ts(row["created_at"]),
            }
            for row in rows[:limit]
        ]
    except Exception as exc:
        logger.exception("Erro em list_suggestions")
        return [{"error": "DB_ERROR", "message": str(exc)}]


def get_history(
    limit: int = 20,
    source: str | None = None,
) -> list[dict]:
    """
    Retorna as últimas N operações do histórico persistido.

    Args:
        limit: Máximo de operações (1–200, padrão 20).
        source: Filtrar por origem: 'ui', 'ai:ollama' ou 'ai:mcp'.
    """
    limit = min(max(1, limit), 200)
    try:
        with _open_db() as db:
            rows = db.list_operations(limit=limit, source=source)
        return [
            {
                "id": row["id"],
                "timestamp": _fmt_ts(row["timestamp"]),
                "operation": row["action"],
                "source_path": row["source_path"],
                "target_path": row["target_path"] or "",
                "success": bool(row["success"]),
                "error": row["error"] or "",
                "used_trash": bool(row["used_trash"]),
                "source": dict(row).get("source", "ui"),
            }
            for row in rows
        ]
    except Exception as exc:
        logger.exception("Erro em get_history")
        return [{"error": "DB_ERROR", "message": str(exc)}]


def get_app_settings() -> dict:
    """
    Retorna todas as configurações persistidas da aplicação como dicionário chave/valor.
    """
    try:
        with _open_db() as db:
            return db.list_settings()
    except Exception as exc:
        logger.exception("Erro em get_app_settings")
        return {"error": "DB_ERROR", "message": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# TOOLS EXECUTIVAS (read_only=False, requires_confirmation=True)
# ─────────────────────────────────────────────────────────────────────────────

def request_confirmation(action: str, args: dict) -> dict:
    """
    Gera um token one-shot para autorizar uma ação executiva.

    Token expira em 60 segundos e só pode ser usado uma vez.
    Retorna: token, expires_at, human_description, risk_level, action.

    Args:
        action: Nome da ação executiva a ser autorizada.
        args:   Argumentos que serão passados à ação.
    """
    _clean_expired_tokens()

    if action not in EXECUTIVE_ACTIONS:
        return {
            "error": "INVALID_ACTION",
            "message": (
                f"'{action}' não é uma ação executiva válida. "
                f"Ações válidas: {sorted(EXECUTIVE_ACTIONS)}"
            ),
        }

    token = secrets.token_hex(16)
    expires_at = time.time() + _TOKEN_TTL_SECONDS
    _token_store[token] = _ConfirmationToken(
        token=token,
        action=action,
        args=args,
        expires_at=expires_at,
    )

    return {
        "token": token,
        "expires_at": _fmt_ts(expires_at),
        "human_description": _describe_action(action, args),
        "risk_level": _assess_risk(action),
        "action": action,
    }


def _describe_action(action: str, args: dict) -> str:
    if action == "move_to_trash":
        name = Path(args.get("path", "?")).name
        return f"Enviar '{name}' para a Lixeira do Windows"
    if action == "move_file":
        name = Path(args.get("source_path", "?")).name
        dst = args.get("target_path", "?")
        return f"Mover '{name}' para '{dst}'"
    if action == "apply_suggestion":
        sid = args.get("suggestion_id", "?")
        return f"Aplicar sugestão #{sid} do SmartRulesEngine"
    if action == "undo_last_operation":
        op_id = args.get("operation_id")
        return f"Desfazer operação #{op_id}" if op_id else "Desfazer a última operação de mover"
    if action == "set_disk_role":
        letter = args.get("drive_letter", "?")
        role = args.get("role", "?")
        return f"Definir disco {letter}: como '{role}'"
    return f"Executar: {action}"


def _assess_risk(action: str) -> str:
    if action in ("move_to_trash", "apply_suggestion"):
        return "medium"
    if action in ("move_file", "undo_last_operation", "set_disk_role"):
        return "low"
    return "high"


def move_to_trash(
    path: str,
    confirmation_token: str,
    ai_source: str = "ai:ollama",
) -> dict:
    """
    Envia um arquivo para a Lixeira do Windows (operação reversível).

    Registra em operation_history com source=ai_source.

    Args:
        path: Caminho absoluto do arquivo a enviar para Lixeira.
        confirmation_token: Token obtido via request_confirmation.
        ai_source: Origem da chamada — 'ai:ollama' ou 'ai:mcp'.
    """
    if err := _validate_token(confirmation_token, "move_to_trash"):
        return err
    if err := _check_rate_limit():
        return err
    if _is_protected(path):
        return {
            "error": "PROTECTED_PATH",
            "message": "Operação negada — caminho é parte do sistema operacional.",
        }

    p = Path(path)
    if not p.exists():
        return {"error": "FILE_NOT_FOUND", "message": f"Arquivo não encontrado: {path}"}

    try:
        used_trash = False
        try:
            from send2trash import send2trash as _send2trash
            _send2trash(str(p))
            used_trash = True
        except ImportError:
            p.unlink()

        _record_exec()
        with _open_db() as db:
            op_id = db.insert_operation(
                timestamp=time.time(),
                action="DELETAR",
                source_path=path,
                success=True,
                used_trash=used_trash,
                source=ai_source,
            )
        return {
            "success": True,
            "path": path,
            "operation_id": op_id,
            "used_trash": used_trash,
            "message": "Arquivo enviado para Lixeira." if used_trash else "Arquivo deletado permanentemente.",
        }
    except PermissionError as exc:
        return {"error": "PERMISSION_DENIED", "message": f"Sem permissão (AV/bloqueio): {exc}"}
    except Exception as exc:
        logger.exception("Erro em move_to_trash: %s", path)
        return {"error": "OPERATION_FAILED", "message": str(exc)}


def move_file(
    source_path: str,
    target_path: str,
    confirmation_token: str,
    ai_source: str = "ai:ollama",
) -> dict:
    """
    Move um arquivo de origem para destino. Cria diretórios intermediários.

    Se o destino já existir, adiciona sufixo numérico para evitar sobrescrita.

    Args:
        source_path: Caminho absoluto de origem.
        target_path: Caminho absoluto de destino (incluindo nome do arquivo).
        confirmation_token: Token obtido via request_confirmation.
        ai_source: Origem da chamada — 'ai:ollama' ou 'ai:mcp'.
    """
    if err := _validate_token(confirmation_token, "move_file"):
        return err
    if err := _check_rate_limit():
        return err
    if _is_protected(source_path):
        return {
            "error": "PROTECTED_PATH",
            "message": "Operação negada — arquivo de origem é parte do sistema operacional.",
        }

    src = Path(source_path)
    if not src.exists():
        return {"error": "FILE_NOT_FOUND", "message": f"Arquivo de origem não encontrado: {source_path}"}

    try:
        dst = Path(target_path)
        dst.parent.mkdir(parents=True, exist_ok=True)

        # Evitar sobrescrever: adicionar sufixo numérico se necessário
        if dst.exists():
            stem, suffix, parent = dst.stem, dst.suffix, dst.parent
            counter = 1
            while dst.exists():
                dst = parent / f"{stem}_{counter}{suffix}"
                counter += 1
            target_path = str(dst)

        shutil.move(str(src), str(dst))
        _record_exec()

        with _open_db() as db:
            op_id = db.insert_operation(
                timestamp=time.time(),
                action="MOVER",
                source_path=source_path,
                target_path=target_path,
                success=True,
                source=ai_source,
            )
        return {
            "success": True,
            "source_path": source_path,
            "target_path": target_path,
            "operation_id": op_id,
            "message": "Arquivo movido com sucesso.",
        }
    except PermissionError as exc:
        return {"error": "PERMISSION_DENIED", "message": f"Sem permissão: {exc}"}
    except Exception as exc:
        logger.exception("Erro em move_file: %s -> %s", source_path, target_path)
        return {"error": "OPERATION_FAILED", "message": str(exc)}


def apply_suggestion(
    suggestion_id: int,
    confirmation_token: str,
    ai_source: str = "ai:ollama",
) -> dict:
    """
    Aplica uma sugestão do SmartRulesEngine pelo seu ID.

    Delega para move_to_trash (DELETAR) ou move_file (MOVER) conforme a
    action da sugestão. Marca a sugestão como executada no banco.

    Args:
        suggestion_id: ID da sugestão (obtido via list_suggestions).
        confirmation_token: Token obtido via request_confirmation.
        ai_source: Origem da chamada — 'ai:ollama' ou 'ai:mcp'.
    """
    if err := _validate_token(confirmation_token, "apply_suggestion"):
        return err
    if err := _check_rate_limit():
        return err

    try:
        with _open_db() as db:
            row = db.get_suggestion_by_id(suggestion_id)

        if not row:
            return {"error": "NOT_FOUND", "message": f"Sugestão #{suggestion_id} não encontrada."}
        if row["executed"]:
            return {
                "error": "ALREADY_EXECUTED",
                "message": f"Sugestão #{suggestion_id} já foi executada anteriormente.",
            }

        file_path = row["file_path"]
        action = row["action"]
        target_disk = row["target_disk"] or ""
        rule_id = row["rule_id"]

        if _is_protected(file_path):
            return {
                "error": "PROTECTED_PATH",
                "message": "Operação negada — arquivo é parte do sistema operacional.",
            }

        p = Path(file_path)
        if not p.exists():
            return {"error": "FILE_NOT_FOUND", "message": f"Arquivo não encontrado: {file_path}"}

        if action == "DELETAR":
            used_trash = False
            try:
                from send2trash import send2trash as _send2trash
                _send2trash(str(p))
                used_trash = True
            except ImportError:
                p.unlink()

            _record_exec()
            with _open_db() as db:
                op_id = db.insert_operation(
                    timestamp=time.time(),
                    action="DELETAR",
                    source_path=file_path,
                    success=True,
                    used_trash=used_trash,
                    source=ai_source,
                )
                db.mark_suggestion_executed(suggestion_id)

            return {
                "success": True,
                "suggestion_id": suggestion_id,
                "operation_id": op_id,
                "message": f"Sugestão R{rule_id} aplicada: arquivo enviado para Lixeira.",
            }

        if action == "MOVER":
            if not target_disk:
                return {
                    "error": "NO_TARGET",
                    "message": "Sugestão não possui disco de destino definido.",
                }
            target_path = str(Path(target_disk + "\\") / p.name)
            dst = Path(target_path)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                stem, suffix, parent = dst.stem, dst.suffix, dst.parent
                counter = 1
                while dst.exists():
                    dst = parent / f"{stem}_{counter}{suffix}"
                    counter += 1
                target_path = str(dst)

            shutil.move(str(p), str(dst))
            _record_exec()

            with _open_db() as db:
                op_id = db.insert_operation(
                    timestamp=time.time(),
                    action="MOVER",
                    source_path=file_path,
                    target_path=target_path,
                    success=True,
                    source=ai_source,
                )
                db.mark_suggestion_executed(suggestion_id)

            return {
                "success": True,
                "suggestion_id": suggestion_id,
                "operation_id": op_id,
                "message": f"Sugestão R{rule_id} aplicada: arquivo movido para {target_path}.",
            }

        return {"error": "UNKNOWN_ACTION", "message": f"Ação '{action}' não reconhecida na sugestão."}

    except Exception as exc:
        logger.exception("Erro em apply_suggestion #%d", suggestion_id)
        return {"error": "OPERATION_FAILED", "message": str(exc)}


def undo_last_operation(
    confirmation_token: str,
    operation_id: int | None = None,
    ai_source: str = "ai:ollama",
) -> dict:
    """
    Desfaz a última operação de MOVER registrada (ou uma específica por ID).

    Move o arquivo de volta de target_path para source_path.
    Operações de Lixeira (DELETAR) devem ser desfeitas manualmente no Windows.

    Args:
        confirmation_token: Token obtido via request_confirmation.
        operation_id: ID específico da operação (padrão: última MOVER bem-sucedida).
        ai_source: Origem da chamada — 'ai:ollama' ou 'ai:mcp'.
    """
    if err := _validate_token(confirmation_token, "undo_last_operation"):
        return err
    if err := _check_rate_limit():
        return err

    try:
        with _open_db() as db:
            if operation_id is not None:
                row = db.get_operation_by_id(operation_id)
                if row and (row["action"] != "MOVER" or not row["success"]):
                    return {
                        "error": "INVALID_OPERATION",
                        "message": f"Operação #{operation_id} não é um MOVER bem-sucedido.",
                    }
            else:
                row = db.get_last_move_operation()

        if not row:
            return {
                "error": "NOT_FOUND",
                "message": "Nenhuma operação de MOVER encontrada para desfazer.",
            }

        current_path = row["target_path"]   # Arquivo está aqui agora
        restore_path = row["source_path"]   # Deve voltar para cá

        if not current_path:
            return {"error": "NO_TARGET", "message": "Operação não possui caminho de destino registrado."}

        if not Path(current_path).exists():
            return {
                "error": "FILE_NOT_FOUND",
                "message": f"Arquivo não encontrado no destino esperado: {current_path}",
            }

        Path(restore_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(current_path, restore_path)
        _record_exec()

        with _open_db() as db:
            op_id = db.insert_operation(
                timestamp=time.time(),
                action="MOVER",
                source_path=current_path,
                target_path=restore_path,
                success=True,
                source=ai_source,
            )

        return {
            "success": True,
            "undone_operation_id": row["id"],
            "new_operation_id": op_id,
            "message": f"Arquivo restaurado para '{restore_path}'.",
        }

    except PermissionError as exc:
        return {"error": "PERMISSION_DENIED", "message": f"Sem permissão: {exc}"}
    except Exception as exc:
        logger.exception("Erro em undo_last_operation")
        return {"error": "OPERATION_FAILED", "message": str(exc)}


def set_disk_role(
    drive_letter: str,
    role: str,
    confirmation_token: str,
    ai_source: str = "ai:ollama",
) -> dict:
    """
    Atribui um papel lógico a um disco. Influencia o SmartRulesEngine.

    Args:
        drive_letter: Letra do disco ('C', 'D', 'C:', 'D:\\', etc.).
        role: Papel — 'primary', 'media', 'backup', 'external' ou 'none'.
        confirmation_token: Token obtido via request_confirmation.
        ai_source: Origem da chamada — 'ai:ollama' ou 'ai:mcp'.
    """
    if err := _validate_token(confirmation_token, "set_disk_role"):
        return err
    if err := _check_rate_limit():
        return err
    if role not in VALID_DISK_ROLES:
        return {
            "error": "INVALID_ROLE",
            "message": f"Papel '{role}' inválido. Válidos: {sorted(VALID_DISK_ROLES)}",
        }
    try:
        with _open_db() as db:
            db.set_disk_role(drive_letter, role)
        _record_exec()
        normalized = drive_letter.strip().upper().rstrip(":\\/") + ":"
        return {
            "success": True,
            "drive_letter": normalized,
            "role": role,
            "message": f"Disco {normalized} definido como '{role}'.",
        }
    except ValueError as exc:
        return {"error": "INVALID_DRIVE", "message": str(exc)}
    except Exception as exc:
        logger.exception("Erro em set_disk_role")
        return {"error": "OPERATION_FAILED", "message": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# Schema JSON das Tools (formato OpenAI/Ollama function-calling)
# ─────────────────────────────────────────────────────────────────────────────

def get_tool_schemas() -> list[dict]:
    """
    Retorna schemas JSON de todas as 12 tools no formato OpenAI/Ollama.

    Uso::

        schemas = get_tool_schemas()
        # Passar para OllamaClient.chat_with_tools() ou ao FastMCP
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "list_partitions",
                "description": "Lista todas as partições do sistema com espaço livre, total e tipo de mídia (NVMe/SSD/HDD).",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "find_top_files",
                "description": "Retorna os N maiores arquivos do índice do último scan, com categoria e caminho.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Quantos arquivos retornar (1–100, padrão 50).",
                        },
                        "category": {
                            "type": "string",
                            "description": "Filtrar por categoria: 'Vídeos', 'Imagens', 'Documentos', 'Executáveis', 'Compactados', 'Outros'.",
                        },
                        "drive_letter": {
                            "type": "string",
                            "description": "Filtrar por letra de disco, ex: 'C' ou 'D:'.",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "find_top_folders",
                "description": "Varre diretórios e retorna os N que mais consomem espaço.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Quantas pastas retornar (1–50, padrão 20).",
                        },
                        "drive_letter": {
                            "type": "string",
                            "description": "Varrer apenas este disco, ex: 'C' ou 'D:'. Omitir para varrer todos.",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "find_duplicates",
                "description": "Retorna grupos de arquivos duplicados do índice, ordenados por espaço desperdiçado.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Máximo de grupos (1–200, padrão 50).",
                        },
                        "min_size_mb": {
                            "type": "number",
                            "description": "Ignorar duplicatas menores que este tamanho em MB (padrão 1.0).",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_suggestions",
                "description": "Retorna sugestões de otimização geradas pelo Motor de Regras no último scan.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "include_dismissed": {
                            "type": "boolean",
                            "description": "Incluir sugestões já descartadas (padrão false).",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Máximo de sugestões (1–100, padrão 20).",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_history",
                "description": "Retorna o histórico de operações realizadas (mover, deletar, desfazer).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Máximo de operações (1–200, padrão 20).",
                        },
                        "source": {
                            "type": "string",
                            "description": "Filtrar por origem: 'ui', 'ai:ollama' ou 'ai:mcp'.",
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_app_settings",
                "description": "Retorna todas as configurações persistidas da aplicação como dicionário chave/valor.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "request_confirmation",
                "description": (
                    "Gera um token one-shot (válido por 60s) para autorizar uma ação executiva. "
                    "SEMPRE chame esta tool antes de qualquer ação executiva (move_to_trash, "
                    "move_file, apply_suggestion, undo_last_operation, set_disk_role). "
                    "Use o token retornado no campo 'confirmation_token' da próxima chamada."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "Nome da ação a autorizar: 'move_to_trash', 'move_file', 'apply_suggestion', 'undo_last_operation' ou 'set_disk_role'.",
                        },
                        "args": {
                            "type": "object",
                            "description": "Argumentos que serão passados à ação (para geração da descrição humana).",
                        },
                    },
                    "required": ["action", "args"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "move_to_trash",
                "description": "Envia um arquivo para a Lixeira do Windows (operação reversível). Requer token de confirmação.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Caminho absoluto do arquivo a enviar para Lixeira.",
                        },
                        "confirmation_token": {
                            "type": "string",
                            "description": "Token obtido via request_confirmation com action='move_to_trash'.",
                        },
                    },
                    "required": ["path", "confirmation_token"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "move_file",
                "description": "Move um arquivo de origem para destino. Requer token de confirmação.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source_path": {
                            "type": "string",
                            "description": "Caminho absoluto do arquivo de origem.",
                        },
                        "target_path": {
                            "type": "string",
                            "description": "Caminho absoluto de destino (incluindo nome do arquivo).",
                        },
                        "confirmation_token": {
                            "type": "string",
                            "description": "Token obtido via request_confirmation com action='move_file'.",
                        },
                    },
                    "required": ["source_path", "target_path", "confirmation_token"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "apply_suggestion",
                "description": "Aplica uma sugestão do Motor de Regras pelo ID. Requer token de confirmação.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "suggestion_id": {
                            "type": "integer",
                            "description": "ID da sugestão (obtido via list_suggestions).",
                        },
                        "confirmation_token": {
                            "type": "string",
                            "description": "Token obtido via request_confirmation com action='apply_suggestion'.",
                        },
                    },
                    "required": ["suggestion_id", "confirmation_token"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "undo_last_operation",
                "description": "Desfaz a última operação de mover (ou uma específica por ID). Requer token de confirmação.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "confirmation_token": {
                            "type": "string",
                            "description": "Token obtido via request_confirmation com action='undo_last_operation'.",
                        },
                        "operation_id": {
                            "type": "integer",
                            "description": "ID específico da operação a desfazer (padrão: última MOVER bem-sucedida).",
                        },
                    },
                    "required": ["confirmation_token"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "set_disk_role",
                "description": "Atribui papel lógico a um disco, influenciando sugestões do Motor de Regras. Requer token.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "drive_letter": {
                            "type": "string",
                            "description": "Letra do disco, ex: 'C', 'D' ou 'D:'.",
                        },
                        "role": {
                            "type": "string",
                            "description": "Papel: 'primary', 'media', 'backup', 'external' ou 'none'.",
                        },
                        "confirmation_token": {
                            "type": "string",
                            "description": "Token obtido via request_confirmation com action='set_disk_role'.",
                        },
                    },
                    "required": ["drive_letter", "role", "confirmation_token"],
                },
            },
        },
    ]
