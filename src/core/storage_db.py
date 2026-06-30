"""
StorageManagerDB — Camada de persistência SQLite do GestaoPC.

Implementa a Fase 1 de persistência: infraestrutura de banco de dados
sem alterar a API pública dos módulos existentes.

Tabelas:
  app_settings       — Configurações chave/valor da aplicação
  disk_roles         — Papéis lógicos dos discos (NVMe, SATA, externo…)
  operation_history  — Histórico persistente de operações (mover/deletar)
  scan_sessions      — Registro de execuções de varredura
  file_index         — Cache/índice de arquivos analisados
  suggestions        — Sugestões geradas pelo motor de regras

Uso básico::

    from src.core.storage_db import StorageManagerDB, get_default_db_path

    with StorageManagerDB(get_default_db_path()) as db:
        db.set_setting("theme", "dark")
        db.set_disk_role("D:", "MASS_STORAGE")

Uso em testes::

    def test_something(tmp_path):
        with StorageManagerDB(tmp_path / "test.db") as db:
            ...
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Caminho padrão do banco
# ---------------------------------------------------------------------------

def get_default_db_path() -> Path:
    """
    Retorna o caminho padrão do banco de dados SQLite.

    Estratégia (Windows-first):

    1. ``%LOCALAPPDATA%/GestaoPC/storage_manager.db``
    2. ``~/.gestaopc/storage_manager.db``  (fallback — Linux/CI)
    """
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "GestaoPC" / "storage_manager.db"
    return Path.home() / ".gestaopc" / "storage_manager.db"


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _normalize_disk_letter(letter: str) -> str:
    """
    Normaliza a letra do disco para o formato padrão ``C:``.

    Aceita: ``c``, ``c:``, ``C:\\``, ``C:/``, ``C:\\\\``
    Retorna sempre: ``C:``
    """
    s = letter.strip().rstrip("\\/").upper()
    if len(s) == 1 and s.isalpha():
        return s + ":"
    if len(s) == 2 and s[0].isalpha() and s[1] == ":":
        return s
    # Tentar extrair letra de caminhos mais longos (ex: "C:\foo")
    if len(s) >= 2 and s[1] == ":":
        return s[:2]
    raise ValueError(f"Letra de disco inválida: {letter!r}")


# ---------------------------------------------------------------------------
# DDL — Definição das tabelas
# ---------------------------------------------------------------------------

_DDL_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS app_settings (
        key        TEXT PRIMARY KEY,
        value      TEXT NOT NULL,
        updated_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS disk_roles (
        letter TEXT PRIMARY KEY,
        role   TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS operation_history (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp         REAL    NOT NULL,
        action            TEXT    NOT NULL,
        source_path       TEXT    NOT NULL,
        target_path       TEXT,
        success           INTEGER NOT NULL,
        error             TEXT,
        used_trash        INTEGER NOT NULL,
        dry_run           INTEGER NOT NULL DEFAULT 0,
        source_size_bytes INTEGER,
        source_mtime      REAL,
        content_hash      TEXT,
        source            TEXT    NOT NULL DEFAULT 'ui'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scan_sessions (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at        REAL    NOT NULL,
        elapsed_seconds   REAL,
        scan_mode         TEXT    NOT NULL,
        total_files_seen  INTEGER DEFAULT 0,
        total_bytes_seen  INTEGER DEFAULT 0,
        error             TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS file_index (
        path         TEXT PRIMARY KEY,
        disk_letter  TEXT,
        size_bytes   INTEGER NOT NULL,
        mtime        REAL    NOT NULL,
        category     TEXT,
        partial_hash TEXT,
        full_hash    TEXT,
        last_seen    REAL    NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS suggestions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_session_id INTEGER,
        rule_id         INTEGER NOT NULL,
        rule_name       TEXT    NOT NULL,
        file_path       TEXT    NOT NULL,
        action          TEXT    NOT NULL,
        detail          TEXT    NOT NULL,
        target_disk     TEXT,
        priority        TEXT    NOT NULL,
        dismissed       INTEGER DEFAULT 0,
        executed        INTEGER DEFAULT 0,
        created_at      REAL    NOT NULL
    )
    """,
    # E7 (Sprint de Escala): índices secundários. Sem eles, as consultas da IA
    # e da GUI faziam full scan + sort no file_index — irrelevante com ~50 linhas,
    # mas crítico quando o índice cresce (E4). CREATE INDEX IF NOT EXISTS é
    # idempotente (migração transparente para bancos existentes).
    "CREATE INDEX IF NOT EXISTS idx_file_index_size ON file_index(size_bytes DESC)",
    "CREATE INDEX IF NOT EXISTS idx_file_index_full_hash ON file_index(full_hash)",
    "CREATE INDEX IF NOT EXISTS idx_file_index_disk ON file_index(disk_letter)",
    "CREATE INDEX IF NOT EXISTS idx_file_index_category ON file_index(category)",
    "CREATE INDEX IF NOT EXISTS idx_operation_history_ts ON operation_history(timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_suggestions_filter ON suggestions(dismissed, created_at DESC)",
]


# ---------------------------------------------------------------------------
# StorageManagerDB
# ---------------------------------------------------------------------------

class StorageManagerDB:
    """
    Camada de acesso ao banco SQLite do GestaoPC Storage Manager.

    Thread-safety: uma instância por thread. Para ambientes multi-thread,
    crie instâncias separadas — sqlite3 em modo ``check_same_thread=True``.
    Para testes simples em thread única, isso é transparente.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    def initialize(self) -> None:
        """
        Abre a conexão e cria todas as tabelas (idempotente).

        Cria o diretório pai do banco se não existir.
        Pode ser chamado múltiplas vezes com segurança.
        """
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        # Chaves estrangeiras e WAL para melhor concorrência de leitura.
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        with self._conn:
            for stmt in _DDL_STATEMENTS:
                self._conn.execute(stmt)

        # Migration: adiciona colunas novas em bancos existentes (idempotente)
        try:
            self._conn.execute(
                "ALTER TABLE operation_history ADD COLUMN source TEXT NOT NULL DEFAULT 'ui'"
            )
            self._conn.commit()
        except sqlite3.OperationalError:
            pass  # Coluna já existe — banco atualizado

        logger.info("StorageManagerDB inicializado: %s", self._db_path)

    def close(self) -> None:
        """Fecha a conexão com o banco de forma segura."""
        if self._conn is not None:
            try:
                self._conn.close()
                logger.debug("StorageManagerDB conexão fechada.")
            except Exception as exc:  # pragma: no cover
                logger.warning("Erro ao fechar conexão SQLite: %s", exc)
            finally:
                self._conn = None

    # Context manager
    def __enter__(self) -> "StorageManagerDB":
        self.initialize()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    @property
    def _db(self) -> sqlite3.Connection:
        """Retorna a conexão, lançando erro se não inicializada."""
        if self._conn is None:
            raise RuntimeError(
                "Banco não inicializado. Chame initialize() ou use o context manager."
            )
        return self._conn

    # ------------------------------------------------------------------ #
    # app_settings                                                         #
    # ------------------------------------------------------------------ #

    def set_setting(self, key: str, value: str) -> None:
        """Salva ou atualiza uma configuração chave/valor."""
        with self._db:
            self._db.execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                               updated_at = excluded.updated_at
                """,
                (key, value, time.time()),
            )

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        """Retorna o valor da configuração, ou ``default`` se não existir."""
        row = self._db.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def delete_setting(self, key: str) -> None:
        """Remove uma configuração pelo nome da chave."""
        with self._db:
            self._db.execute("DELETE FROM app_settings WHERE key = ?", (key,))

    def list_settings(self) -> dict[str, str]:
        """Retorna todas as configurações como dicionário."""
        rows = self._db.execute("SELECT key, value FROM app_settings").fetchall()
        return {row["key"]: row["value"] for row in rows}

    # ------------------------------------------------------------------ #
    # disk_roles                                                           #
    # ------------------------------------------------------------------ #

    def set_disk_role(self, letter: str, role: str) -> None:
        """Salva ou atualiza o papel lógico de um disco."""
        normalized = _normalize_disk_letter(letter)
        with self._db:
            self._db.execute(
                """
                INSERT INTO disk_roles (letter, role)
                VALUES (?, ?)
                ON CONFLICT(letter) DO UPDATE SET role = excluded.role
                """,
                (normalized, role),
            )

    def get_disk_role(self, letter: str, default: str | None = None) -> str | None:
        """Retorna o papel de um disco, ou ``default`` se não configurado."""
        normalized = _normalize_disk_letter(letter)
        row = self._db.execute(
            "SELECT role FROM disk_roles WHERE letter = ?", (normalized,)
        ).fetchone()
        return row["role"] if row else default

    def list_disk_roles(self) -> dict[str, str]:
        """Retorna todos os papéis de disco como ``{letra: papel}``."""
        rows = self._db.execute("SELECT letter, role FROM disk_roles").fetchall()
        return {row["letter"]: row["role"] for row in rows}

    def delete_disk_role(self, letter: str) -> None:
        """Remove o papel configurado de um disco."""
        normalized = _normalize_disk_letter(letter)
        with self._db:
            self._db.execute(
                "DELETE FROM disk_roles WHERE letter = ?", (normalized,)
            )

    # ------------------------------------------------------------------ #
    # operation_history                                                    #
    # ------------------------------------------------------------------ #

    def insert_operation(
        self,
        *,
        timestamp: float,
        action: str,
        source_path: str,
        target_path: str | None = None,
        success: bool,
        error: str | None = None,
        used_trash: bool = False,
        dry_run: bool = False,
        source_size_bytes: int | None = None,
        source_mtime: float | None = None,
        content_hash: str | None = None,
        source: str = "ui",
    ) -> int:
        """
        Insere um registro de operação no histórico persistente.

        Parameters
        ----------
        source:
            Origem da operação: ``'ui'`` (interface gráfica),
            ``'ai:ollama'`` (assistente local) ou ``'ai:mcp'`` (cliente MCP externo).

        Retorna o ``id`` gerado pelo banco.
        """
        with self._db:
            cur = self._db.execute(
                """
                INSERT INTO operation_history (
                    timestamp, action, source_path, target_path,
                    success, error, used_trash, dry_run,
                    source_size_bytes, source_mtime, content_hash, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    action,
                    source_path,
                    target_path,
                    int(success),
                    error,
                    int(used_trash),
                    int(dry_run),
                    source_size_bytes,
                    source_mtime,
                    content_hash,
                    source,
                ),
            )
        return cur.lastrowid  # type: ignore[return-value]

    def list_operations(
        self,
        limit: int | None = None,
        source: str | None = None,
    ) -> list[sqlite3.Row]:
        """
        Retorna operações do histórico, mais recentes primeiro.

        Parameters
        ----------
        limit:
            Quantidade máxima de registros a retornar. None = todos.
        source:
            Se fornecido, filtra por origem: ``'ui'``, ``'ai:ollama'`` ou ``'ai:mcp'``.
        """
        conditions: list[str] = []
        params: list[Any] = []
        if source is not None:
            conditions.append("source = ?")
            params.append(source)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        order_limit = "ORDER BY timestamp DESC"
        if limit is not None:
            order_limit += " LIMIT ?"
            params.append(limit)

        rows = self._db.execute(
            f"SELECT * FROM operation_history {where} {order_limit}",  # noqa: S608
            params,
        ).fetchall()
        return list(rows)

    def get_operation_by_id(self, operation_id: int) -> sqlite3.Row | None:
        """Retorna uma operação pelo id, ou None se não existir."""
        return self._db.execute(
            "SELECT * FROM operation_history WHERE id = ?", (operation_id,)
        ).fetchone()

    def get_last_move_operation(self) -> sqlite3.Row | None:
        """Retorna a última operação de MOVER bem-sucedida, ou None."""
        return self._db.execute(
            "SELECT * FROM operation_history WHERE action = 'MOVER' AND success = 1 "
            "ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()

    def clear_operations(self) -> None:
        """Remove todo o histórico de operações."""
        with self._db:
            self._db.execute("DELETE FROM operation_history")

    # ------------------------------------------------------------------ #
    # scan_sessions                                                        #
    # ------------------------------------------------------------------ #

    def create_scan_session(
        self,
        *,
        started_at: float,
        scan_mode: str,
        total_files_seen: int = 0,
        total_bytes_seen: int = 0,
        error: str | None = None,
    ) -> int:
        """
        Cria uma nova sessão de varredura e retorna seu ``id``.

        Deve ser chamado ao INICIAR a varredura; use ``finish_scan_session``
        para atualizar os dados ao terminar.
        """
        with self._db:
            cur = self._db.execute(
                """
                INSERT INTO scan_sessions (
                    started_at, scan_mode,
                    total_files_seen, total_bytes_seen, error
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (started_at, scan_mode, total_files_seen, total_bytes_seen, error),
            )
        return cur.lastrowid  # type: ignore[return-value]

    def finish_scan_session(
        self,
        session_id: int,
        *,
        elapsed_seconds: float,
        total_files_seen: int | None = None,
        total_bytes_seen: int | None = None,
        error: str | None = None,
    ) -> None:
        """Atualiza uma sessão de varredura com o resultado final."""
        fields: list[str] = ["elapsed_seconds = ?"]
        params: list[Any] = [elapsed_seconds]

        if total_files_seen is not None:
            fields.append("total_files_seen = ?")
            params.append(total_files_seen)
        if total_bytes_seen is not None:
            fields.append("total_bytes_seen = ?")
            params.append(total_bytes_seen)
        if error is not None:
            fields.append("error = ?")
            params.append(error)

        params.append(session_id)
        with self._db:
            self._db.execute(
                f"UPDATE scan_sessions SET {', '.join(fields)} WHERE id = ?",  # noqa: S608
                params,
            )

    def get_scan_session(self, session_id: int) -> sqlite3.Row | None:
        """Retorna uma sessão de varredura pelo id, ou None se não existir."""
        return self._db.execute(
            "SELECT * FROM scan_sessions WHERE id = ?", (session_id,)
        ).fetchone()

    # ------------------------------------------------------------------ #
    # file_index                                                           #
    # ------------------------------------------------------------------ #

    def upsert_file_index(
        self,
        *,
        path: str,
        disk_letter: str | None,
        size_bytes: int,
        mtime: float,
        category: str | None = None,
        partial_hash: str | None = None,
        full_hash: str | None = None,
        last_seen: float,
    ) -> None:
        """
        Insere ou atualiza uma entrada no índice de arquivos.

        Se o caminho já existir, todos os campos são atualizados.
        """
        with self._db:
            self._db.execute(
                """
                INSERT INTO file_index (
                    path, disk_letter, size_bytes, mtime,
                    category, partial_hash, full_hash, last_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    disk_letter  = excluded.disk_letter,
                    size_bytes   = excluded.size_bytes,
                    mtime        = excluded.mtime,
                    category     = excluded.category,
                    partial_hash = excluded.partial_hash,
                    full_hash    = excluded.full_hash,
                    last_seen    = excluded.last_seen
                """,
                (
                    path, disk_letter, size_bytes, mtime,
                    category, partial_hash, full_hash, last_seen,
                ),
            )

    def upsert_file_index_many(
        self, rows: list[tuple[str, str | None, int, float, str | None,
                               str | None, str | None, float]]
    ) -> int:
        """
        E4 (Sprint de Escala): upsert em LOTE no file_index, numa única
        transação (executemany), em vez de um commit/fsync por arquivo.

        Cada tupla: (path, disk_letter, size_bytes, mtime, category,
        partial_hash, full_hash, last_seen). Retorna o nº de linhas processadas.

        Necessário porque E4 passa a persistir TODO o conjunto varrido (não só
        o top-50), o que tornaria o upsert linha-a-linha custoso.
        """
        if not rows:
            return 0
        with self._db:
            self._db.executemany(
                """
                INSERT INTO file_index (
                    path, disk_letter, size_bytes, mtime,
                    category, partial_hash, full_hash, last_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    disk_letter  = excluded.disk_letter,
                    size_bytes   = excluded.size_bytes,
                    mtime        = excluded.mtime,
                    category     = excluded.category,
                    partial_hash = excluded.partial_hash,
                    full_hash    = excluded.full_hash,
                    last_seen    = excluded.last_seen
                """,
                rows,
            )
        return len(rows)

    def get_file_index(self, path: str) -> sqlite3.Row | None:
        """Retorna a entrada do índice para um caminho, ou None."""
        return self._db.execute(
            "SELECT * FROM file_index WHERE path = ?", (path,)
        ).fetchone()

    def get_file_index_batch(
        self, paths: list[str]
    ) -> dict[str, sqlite3.Row]:
        """
        Sprint 7.4: lookup em lote para o cache de hash.

        Faz UMA query SELECT ... WHERE path IN (?, ?, ...) e retorna um dict
        path → row. Evita N round-trips ao SQLite quando o detector precisa
        consultar centenas de candidatos.

        SQLite limita 999 placeholders por query (compile-time
        SQLITE_MAX_VARIABLE_NUMBER); fazemos chunking em batches de 500.
        """
        if not paths:
            return {}

        result: dict[str, sqlite3.Row] = {}
        BATCH = 500
        for i in range(0, len(paths), BATCH):
            chunk = paths[i:i + BATCH]
            placeholders = ",".join("?" * len(chunk))
            rows = self._db.execute(
                f"SELECT * FROM file_index WHERE path IN ({placeholders})",  # noqa: S608
                chunk,
            ).fetchall()
            for row in rows:
                result[row["path"]] = row
        return result

    def update_file_hashes_batch(
        self, updates: list[tuple[str, str | None, str | None]]
    ) -> int:
        """
        Sprint 7.4: persistência em lote dos hashes recém-computados.

        Recebe uma lista de tuplas (path, partial_hash, full_hash) onde os
        hashes podem ser None (significa "não atualizar este campo"). Faz
        UPDATE atômico em uma transação. Retorna a quantidade de linhas
        afetadas.

        Ignora silenciosamente paths que não existem na tabela — o caller
        deve garantir que chamou upsert_file_index antes para criar a row.
        """
        if not updates:
            return 0
        affected = 0
        with self._db:
            for path, partial, full in updates:
                # Construir UPDATE dinâmico para evitar sobrescrever com None
                fields: list[str] = []
                values: list = []
                if partial is not None:
                    fields.append("partial_hash = ?")
                    values.append(partial)
                if full is not None:
                    fields.append("full_hash = ?")
                    values.append(full)
                if not fields:
                    continue
                values.append(path)
                cur = self._db.execute(
                    f"UPDATE file_index SET {', '.join(fields)} WHERE path = ?",  # noqa: S608
                    values,
                )
                affected += cur.rowcount
        return affected

    def remove_file_index(self, path: str) -> None:
        """Remove uma entrada do índice pelo caminho."""
        with self._db:
            self._db.execute("DELETE FROM file_index WHERE path = ?", (path,))

    def remove_missing_file_index_entries(self) -> int:
        """
        Remove entradas do índice cujo arquivo não existe mais no filesystem.

        Retorna a quantidade de entradas removidas.
        """
        rows = self._db.execute("SELECT path FROM file_index").fetchall()
        to_remove = [row["path"] for row in rows if not Path(row["path"]).exists()]
        if to_remove:
            with self._db:
                self._db.executemany(
                    "DELETE FROM file_index WHERE path = ?",
                    [(p,) for p in to_remove],
                )
        logger.info(
            "remove_missing_file_index_entries: %d entradas órfãs removidas.",
            len(to_remove),
        )
        return len(to_remove)

    # ------------------------------------------------------------------ #
    # suggestions                                                          #
    # ------------------------------------------------------------------ #

    def insert_suggestion(
        self,
        *,
        scan_session_id: int | None,
        rule_id: int,
        rule_name: str,
        file_path: str,
        action: str,
        detail: str,
        target_disk: str | None,
        priority: str,
        created_at: float,
    ) -> int:
        """Insere uma sugestão gerada pelo motor de regras. Retorna o id."""
        with self._db:
            cur = self._db.execute(
                """
                INSERT INTO suggestions (
                    scan_session_id, rule_id, rule_name, file_path,
                    action, detail, target_disk, priority, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scan_session_id, rule_id, rule_name, file_path,
                    action, detail, target_disk, priority, created_at,
                ),
            )
        return cur.lastrowid  # type: ignore[return-value]

    def list_suggestions(
        self,
        scan_session_id: int | None = None,
        include_dismissed: bool = False,
    ) -> list[sqlite3.Row]:
        """
        Retorna sugestões armazenadas.

        Parameters
        ----------
        scan_session_id:
            Se fornecido, filtra por sessão de varredura.
        include_dismissed:
            Se False (padrão), oculta sugestões marcadas como dispensadas.
        """
        conditions: list[str] = []
        params: list[Any] = []

        if scan_session_id is not None:
            conditions.append("scan_session_id = ?")
            params.append(scan_session_id)
        if not include_dismissed:
            conditions.append("dismissed = 0")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self._db.execute(
            f"SELECT * FROM suggestions {where} ORDER BY created_at DESC",  # noqa: S608
            params,
        ).fetchall()
        return list(rows)

    def mark_suggestion_executed(self, suggestion_id: int) -> None:
        """Marca uma sugestão como executada."""
        with self._db:
            self._db.execute(
                "UPDATE suggestions SET executed = 1 WHERE id = ?", (suggestion_id,)
            )

    def mark_suggestion_dismissed(self, suggestion_id: int) -> None:
        """Marca uma sugestão como dispensada (não aparece nas listagens padrão)."""
        with self._db:
            self._db.execute(
                "UPDATE suggestions SET dismissed = 1 WHERE id = ?", (suggestion_id,)
            )

    def get_suggestion_by_id(self, suggestion_id: int) -> sqlite3.Row | None:
        """Retorna uma sugestão pelo id, ou None se não existir."""
        return self._db.execute(
            "SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)
        ).fetchone()

    def clear_suggestions(self) -> None:
        """Remove todas as sugestões armazenadas."""
        with self._db:
            self._db.execute("DELETE FROM suggestions")

    # ------------------------------------------------------------------ #
    # file_index — métodos adicionais para AI Toolbelt                    #
    # ------------------------------------------------------------------ #

    def list_file_index(
        self,
        limit: int = 100,
        category: str | None = None,
        disk_letter: str | None = None,
    ) -> list[sqlite3.Row]:
        """
        Retorna entradas do índice de arquivos ordenadas por tamanho (maior primeiro).

        Parameters
        ----------
        limit:
            Máximo de registros a retornar (máx. 100).
        category:
            Filtrar por categoria (ex: ``'Vídeos'``, ``'Imagens'``).
        disk_letter:
            Filtrar por letra de disco (ex: ``'C:'``).
        """
        conditions: list[str] = []
        params: list[Any] = []
        if category:
            conditions.append("category = ?")
            params.append(category)
        if disk_letter:
            normalized = disk_letter.strip().upper().rstrip(":\\/")
            if normalized:
                normalized += ":"
                conditions.append("disk_letter = ?")
                params.append(normalized)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(min(max(1, limit), 100))
        rows = self._db.execute(
            f"SELECT * FROM file_index {where} ORDER BY size_bytes DESC LIMIT ?",  # noqa: S608
            params,
        ).fetchall()
        return list(rows)

    def find_duplicates_from_index(
        self,
        limit: int = 50,
        min_size_bytes: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Agrupa arquivos do índice por hash completo e retorna grupos duplicados.

        Retorna lista de dicts ordenada pelo espaço desperdiçado (maior primeiro).
        Cada dict contém: hash, file_count, size_each_bytes, wasted_bytes, files.
        """
        from collections import defaultdict

        rows = self._db.execute(
            "SELECT full_hash, size_bytes, path FROM file_index "
            "WHERE full_hash IS NOT NULL AND size_bytes >= ? "
            "ORDER BY size_bytes DESC",
            (min_size_bytes,),
        ).fetchall()

        groups: dict[str, list[str]] = defaultdict(list)
        size_map: dict[str, int] = {}
        for row in rows:
            h = row["full_hash"]
            groups[h].append(row["path"])
            size_map[h] = row["size_bytes"]

        result: list[dict[str, Any]] = []
        for hash_val, paths in groups.items():
            if len(paths) >= 2:
                size = size_map[hash_val]
                result.append(
                    {
                        "hash": hash_val,
                        "file_count": len(paths),
                        "size_each_bytes": size,
                        "wasted_bytes": size * (len(paths) - 1),
                        "files": sorted(paths),
                    }
                )

        result.sort(key=lambda x: x["wasted_bytes"], reverse=True)
        return result[:limit]
