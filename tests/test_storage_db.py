"""
Testes — StorageManagerDB (Fase 1 de persistência SQLite).

Cobertura:
  1.  Criação do banco e das tabelas
  2.  initialize() idempotente
  3.  Context manager
  4.  Salvar/carregar setting
  5.  Valor default de setting inexistente
  6.  Deletar setting
  7.  Salvar/listar/deletar disk role
  8.  Normalização de letras de disco
  9.  Inserir/listar operação
  10. Operações listadas em ordem mais recente primeiro
  11. Limpar histórico
  12. Criar/finalizar scan session
  13. Obter scan session por id
  14. Upsert em file_index
  15. Atualizar hash em file_index (upsert duplo)
  16. Remover entrada de file_index
  17. Remover entradas órfãs de file_index
  18. Inserir/listar sugestão
  19. Filtrar sugestões por scan_session_id
  20. Marcar sugestão como executada
  21. Marcar sugestão como dispensada
  22. include_dismissed=True retorna dispensadas
  23. Persistência entre duas instâncias diferentes
"""

from __future__ import annotations

import time

import pytest

from src.core.storage_db import StorageManagerDB, _normalize_disk_letter, get_default_db_path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    """Banco de dados limpo para cada teste."""
    with StorageManagerDB(tmp_path / "test.db") as database:
        yield database


@pytest.fixture
def db_path(tmp_path):
    """Apenas o caminho, sem instância aberta."""
    return tmp_path / "persist_test.db"


# ---------------------------------------------------------------------------
# Helpers de fábrica
# ---------------------------------------------------------------------------

def _insert_op(database: StorageManagerDB, **overrides) -> int:
    defaults = dict(
        timestamp=time.time(),
        action="MOVER",
        source_path="C:/foo.txt",
        target_path="D:/foo.txt",
        success=True,
    )
    defaults.update(overrides)
    return database.insert_operation(**defaults)


def _insert_sug(database: StorageManagerDB, **overrides) -> int:
    defaults = dict(
        scan_session_id=None,
        rule_id=1,
        rule_name="Mídia pesada no NVMe",
        file_path="C:/video.mkv",
        action="MOVER",
        detail="Mover para D:",
        target_disk="D:",
        priority="ALTA",
        created_at=time.time(),
    )
    defaults.update(overrides)
    return database.insert_suggestion(**defaults)


# ===========================================================================
# 1. Criação do banco e das tabelas
# ===========================================================================

def test_db_file_is_created(tmp_path):
    db_path = tmp_path / "sub" / "new.db"
    with StorageManagerDB(db_path):
        pass
    assert db_path.exists(), "Arquivo .db deve ser criado"


def test_all_tables_exist(db):
    tables = {
        row[0]
        for row in db._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    expected = {
        "app_settings", "disk_roles", "operation_history",
        "scan_sessions", "file_index", "suggestions",
    }
    assert expected.issubset(tables)


def test_operation_history_has_dry_run_column(db):
    cols = {
        row[1]
        for row in db._db.execute("PRAGMA table_info(operation_history)").fetchall()
    }
    assert "dry_run" in cols
    assert "source_size_bytes" in cols
    assert "source_mtime" in cols
    assert "content_hash" in cols


def test_secondary_indexes_exist(db):
    """E7: índices secundários criados (idempotentes)."""
    indexes = {
        row[0]
        for row in db._db.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
    }
    expected = {
        "idx_file_index_size",
        "idx_file_index_full_hash",
        "idx_file_index_disk",
        "idx_file_index_category",
        "idx_operation_history_ts",
        "idx_suggestions_filter",
    }
    assert expected.issubset(indexes), f"faltando: {expected - indexes}"


# ===========================================================================
# 2. initialize() idempotente
# ===========================================================================

def test_initialize_twice_is_safe(tmp_path):
    db_path = tmp_path / "idem.db"
    db1 = StorageManagerDB(db_path)
    db1.initialize()
    db1.initialize()  # Segunda chamada não deve lançar exceção
    db1.set_setting("k", "v")
    assert db1.get_setting("k") == "v"
    db1.close()


# ===========================================================================
# 3. Context manager
# ===========================================================================

def test_context_manager_opens_and_closes(tmp_path):
    db_path = tmp_path / "ctx.db"
    with StorageManagerDB(db_path) as database:
        database.set_setting("hello", "world")
        assert database.get_setting("hello") == "world"
    # Após saída do context, conexão deve estar fechada
    assert database._conn is None


def test_use_after_close_raises(tmp_path):
    db_path = tmp_path / "closed.db"
    database = StorageManagerDB(db_path)
    database.initialize()
    database.close()
    with pytest.raises(RuntimeError, match="não inicializado"):
        database.get_setting("x")


# ===========================================================================
# 4. Salvar / carregar setting
# ===========================================================================

def test_set_and_get_setting(db):
    db.set_setting("theme", "dark")
    assert db.get_setting("theme") == "dark"


def test_update_existing_setting(db):
    db.set_setting("lang", "pt-BR")
    db.set_setting("lang", "en-US")
    assert db.get_setting("lang") == "en-US"


def test_list_settings_returns_all(db):
    db.set_setting("a", "1")
    db.set_setting("b", "2")
    result = db.list_settings()
    assert result == {"a": "1", "b": "2"}


# ===========================================================================
# 5. Valor default de setting inexistente
# ===========================================================================

def test_get_setting_default_none(db):
    assert db.get_setting("missing") is None


def test_get_setting_custom_default(db):
    assert db.get_setting("missing", "fallback") == "fallback"


# ===========================================================================
# 6. Deletar setting
# ===========================================================================

def test_delete_setting(db):
    db.set_setting("tmp", "x")
    db.delete_setting("tmp")
    assert db.get_setting("tmp") is None


def test_delete_nonexistent_setting_is_safe(db):
    db.delete_setting("ghost")  # Não deve lançar exceção


# ===========================================================================
# 7. Salvar / listar / deletar disk role
# ===========================================================================

def test_set_and_get_disk_role(db):
    db.set_disk_role("D:", "MASS_STORAGE")
    assert db.get_disk_role("D:") == "MASS_STORAGE"


def test_update_existing_disk_role(db):
    db.set_disk_role("C:", "SYSTEM")
    db.set_disk_role("C:", "FAST_STORAGE")
    assert db.get_disk_role("C:") == "FAST_STORAGE"


def test_list_disk_roles(db):
    db.set_disk_role("C:", "SYSTEM")
    db.set_disk_role("D:", "MASS_STORAGE")
    roles = db.list_disk_roles()
    assert roles == {"C:": "SYSTEM", "D:": "MASS_STORAGE"}


def test_delete_disk_role(db):
    db.set_disk_role("G:", "BACKUP")
    db.delete_disk_role("G:")
    assert db.get_disk_role("G:") is None


def test_get_disk_role_default(db):
    assert db.get_disk_role("Z:", "UNKNOWN") == "UNKNOWN"


# ===========================================================================
# 8. Normalização de letras de disco
# ===========================================================================

@pytest.mark.parametrize("raw, expected", [
    ("c",    "C:"),
    ("c:",   "C:"),
    ("C:",   "C:"),
    ("C:\\", "C:"),
    ("C:/",  "C:"),
    ("d",    "D:"),
    ("D:",   "D:"),
    ("j:\\", "J:"),
])
def test_normalize_disk_letter(raw, expected):
    assert _normalize_disk_letter(raw) == expected


def test_normalize_invalid_letter_raises():
    with pytest.raises(ValueError):
        _normalize_disk_letter("invalid_path_without_drive")


def test_set_disk_role_normalizes_input(db):
    """set_disk_role deve aceitar formatos não normalizados."""
    db.set_disk_role("c:\\", "SYSTEM")
    assert db.get_disk_role("C:") == "SYSTEM"


# ===========================================================================
# 9. Inserir / listar operação
# ===========================================================================

def test_insert_operation_returns_id(db):
    op_id = _insert_op(db)
    assert isinstance(op_id, int)
    assert op_id >= 1


def test_list_operations_contains_inserted(db):
    _insert_op(db, source_path="C:/a.txt", action="MOVER")
    rows = db.list_operations()
    assert len(rows) == 1
    assert rows[0]["source_path"] == "C:/a.txt"
    assert rows[0]["action"] == "MOVER"


def test_insert_operation_all_optional_fields(db):
    op_id = db.insert_operation(
        timestamp=1234567890.0,
        action="DELETAR",
        source_path="C:/video.mkv",
        target_path=None,
        success=False,
        error="PermissionError",
        used_trash=True,
        dry_run=True,
        source_size_bytes=2_000_000_000,
        source_mtime=1234560000.0,
        content_hash="abc123",
    )
    assert op_id > 0, "insert_operation deve retornar o id gerado pelo banco"
    row = db.list_operations()[0]
    assert row["error"] == "PermissionError"
    assert bool(row["used_trash"]) is True
    assert bool(row["dry_run"]) is True
    assert row["source_size_bytes"] == 2_000_000_000
    assert row["content_hash"] == "abc123"


# ===========================================================================
# 10. Operações listadas em ordem mais recente primeiro
# ===========================================================================

def test_list_operations_most_recent_first(db):
    _insert_op(db, timestamp=1000.0, source_path="C:/old.txt")
    _insert_op(db, timestamp=3000.0, source_path="C:/new.txt")
    _insert_op(db, timestamp=2000.0, source_path="C:/mid.txt")
    rows = db.list_operations()
    timestamps = [row["timestamp"] for row in rows]
    assert timestamps == sorted(timestamps, reverse=True)
    assert rows[0]["source_path"] == "C:/new.txt"


def test_list_operations_with_limit(db):
    for i in range(10):
        _insert_op(db, timestamp=float(i))
    rows = db.list_operations(limit=3)
    assert len(rows) == 3


# ===========================================================================
# 11. Limpar histórico
# ===========================================================================

def test_clear_operations(db):
    _insert_op(db)
    _insert_op(db)
    db.clear_operations()
    assert db.list_operations() == []


# ===========================================================================
# 12. Criar / finalizar scan session
# ===========================================================================

def test_create_scan_session_returns_id(db):
    sid = db.create_scan_session(started_at=time.time(), scan_mode="QUICK")
    assert isinstance(sid, int)
    assert sid >= 1


def test_finish_scan_session_updates_fields(db):
    sid = db.create_scan_session(started_at=1000.0, scan_mode="FULL")
    db.finish_scan_session(
        sid,
        elapsed_seconds=42.5,
        total_files_seen=500,
        total_bytes_seen=1_000_000,
    )
    row = db.get_scan_session(sid)
    assert row["elapsed_seconds"] == 42.5
    assert row["total_files_seen"] == 500
    assert row["total_bytes_seen"] == 1_000_000


def test_finish_scan_session_with_error(db):
    sid = db.create_scan_session(started_at=1000.0, scan_mode="QUICK")
    db.finish_scan_session(sid, elapsed_seconds=1.0, error="Timeout")
    row = db.get_scan_session(sid)
    assert row["error"] == "Timeout"


# ===========================================================================
# 13. Obter scan session por id
# ===========================================================================

def test_get_scan_session_existing(db):
    sid = db.create_scan_session(started_at=9999.0, scan_mode="DEEP")
    row = db.get_scan_session(sid)
    assert row is not None
    assert row["scan_mode"] == "DEEP"
    assert row["started_at"] == 9999.0


def test_get_scan_session_nonexistent(db):
    assert db.get_scan_session(99999) is None


# ===========================================================================
# 14. Upsert em file_index
# ===========================================================================

def test_upsert_file_index_inserts(db, tmp_path):
    filepath = str(tmp_path / "video.mkv")
    db.upsert_file_index(
        path=filepath,
        disk_letter="C:",
        size_bytes=2_000_000_000,
        mtime=1234567890.0,
        category="Vídeos",
        last_seen=time.time(),
    )
    row = db.get_file_index(filepath)
    assert row is not None
    assert row["disk_letter"] == "C:"
    assert row["category"] == "Vídeos"
    assert row["size_bytes"] == 2_000_000_000


# ===========================================================================
# 15. Atualizar hash em file_index (upsert duplo)
# ===========================================================================

def test_upsert_file_index_updates_hash(db, tmp_path):
    filepath = str(tmp_path / "doc.pdf")
    db.upsert_file_index(
        path=filepath, disk_letter="D:", size_bytes=100,
        mtime=1000.0, last_seen=1000.0,
    )
    # Segunda chamada atualiza o hash
    db.upsert_file_index(
        path=filepath, disk_letter="D:", size_bytes=100,
        mtime=1000.0, partial_hash="abc123", full_hash="sha256abc",
        last_seen=2000.0,
    )
    row = db.get_file_index(filepath)
    assert row["partial_hash"] == "abc123"
    assert row["full_hash"] == "sha256abc"
    assert row["last_seen"] == 2000.0


def test_upsert_file_index_many_inserts_and_updates(db):
    """E4: upsert em lote insere e, na 2ª chamada, atualiza (enriquece hash)."""
    rows = [
        ("G:/a.iso", "G:", 1000, 10.0, "Compactados", None, None, 1.0),
        ("G:/b.iso", "G:", 2000, 20.0, "Compactados", None, None, 1.0),
    ]
    assert db.upsert_file_index_many(rows) == 2
    assert {r["path"] for r in db.list_file_index(limit=100)} == {"G:/a.iso", "G:/b.iso"}
    assert db.get_file_index("G:/a.iso")["full_hash"] is None

    # 2ª chamada: mesmo path 'a' com full_hash → enriquece sem duplicar.
    db.upsert_file_index_many(
        [("G:/a.iso", "G:", 1000, 10.0, "Compactados", "p", "FULLHASH", 2.0)]
    )
    assert len(db.list_file_index(limit=100)) == 2
    assert db.get_file_index("G:/a.iso")["full_hash"] == "FULLHASH"


def test_upsert_file_index_many_empty_is_noop(db):
    assert db.upsert_file_index_many([]) == 0
    assert db.list_file_index(limit=10) == []


# ===========================================================================
# 16. Remover entrada de file_index
# ===========================================================================

def test_remove_file_index(db, tmp_path):
    filepath = str(tmp_path / "removeme.txt")
    db.upsert_file_index(
        path=filepath, disk_letter="C:", size_bytes=10,
        mtime=1.0, last_seen=1.0,
    )
    db.remove_file_index(filepath)
    assert db.get_file_index(filepath) is None


def test_remove_file_index_nonexistent_is_safe(db):
    db.remove_file_index("C:/ghost.txt")  # Não deve lançar exceção


# ===========================================================================
# 17. Remover entradas órfãs de file_index
# ===========================================================================

def test_remove_missing_file_index_entries(db, tmp_path):
    real_file = tmp_path / "real.txt"
    real_file.write_text("exists")
    ghost_path = str(tmp_path / "ghost.txt")  # Não existe

    db.upsert_file_index(
        path=str(real_file), disk_letter="C:", size_bytes=5,
        mtime=1.0, last_seen=1.0,
    )
    db.upsert_file_index(
        path=ghost_path, disk_letter="C:", size_bytes=5,
        mtime=1.0, last_seen=1.0,
    )
    removed = db.remove_missing_file_index_entries()
    assert removed == 1
    assert db.get_file_index(str(real_file)) is not None
    assert db.get_file_index(ghost_path) is None


def test_remove_missing_returns_zero_when_all_exist(db, tmp_path):
    real_file = tmp_path / "exists.txt"
    real_file.write_text("ok")
    db.upsert_file_index(
        path=str(real_file), disk_letter="D:", size_bytes=2,
        mtime=1.0, last_seen=1.0,
    )
    assert db.remove_missing_file_index_entries() == 0


# ===========================================================================
# 18. Inserir / listar sugestão
# ===========================================================================

def test_insert_suggestion_returns_id(db):
    sug_id = _insert_sug(db)
    assert isinstance(sug_id, int)
    assert sug_id >= 1


def test_list_suggestions_contains_inserted(db):
    _insert_sug(db, file_path="C:/a.mkv", rule_id=1)
    rows = db.list_suggestions()
    assert len(rows) == 1
    assert rows[0]["file_path"] == "C:/a.mkv"
    assert rows[0]["rule_id"] == 1


# ===========================================================================
# 19. Filtrar sugestões por scan_session_id
# ===========================================================================

def test_list_suggestions_filter_by_session(db):
    sid1 = db.create_scan_session(started_at=1.0, scan_mode="QUICK")
    sid2 = db.create_scan_session(started_at=2.0, scan_mode="FULL")

    _insert_sug(db, scan_session_id=sid1, file_path="C:/a.mkv")
    _insert_sug(db, scan_session_id=sid1, file_path="C:/b.mkv")
    _insert_sug(db, scan_session_id=sid2, file_path="D:/c.mkv")

    rows_s1 = db.list_suggestions(scan_session_id=sid1)
    assert len(rows_s1) == 2

    rows_s2 = db.list_suggestions(scan_session_id=sid2)
    assert len(rows_s2) == 1
    assert rows_s2[0]["file_path"] == "D:/c.mkv"


# ===========================================================================
# 20. Marcar sugestão como executada
# ===========================================================================

def test_mark_suggestion_executed(db):
    sug_id = _insert_sug(db)
    db.mark_suggestion_executed(sug_id)
    row = db._db.execute(
        "SELECT executed FROM suggestions WHERE id = ?", (sug_id,)
    ).fetchone()
    assert row["executed"] == 1


# ===========================================================================
# 21. Marcar sugestão como dispensada (oculta na listagem padrão)
# ===========================================================================

def test_mark_suggestion_dismissed_hides_from_default_list(db):
    sug_id = _insert_sug(db)
    db.mark_suggestion_dismissed(sug_id)
    rows = db.list_suggestions()
    assert len(rows) == 0


# ===========================================================================
# 22. include_dismissed=True retorna dispensadas
# ===========================================================================

def test_include_dismissed_true_returns_dismissed(db):
    sug_id = _insert_sug(db)
    db.mark_suggestion_dismissed(sug_id)
    rows = db.list_suggestions(include_dismissed=True)
    assert len(rows) == 1
    assert rows[0]["dismissed"] == 1


def test_list_suggestions_mixes_dismissed_and_active(db):
    _insert_sug(db, file_path="C:/active.mkv")
    dismissed_id = _insert_sug(db, file_path="C:/dismissed.mkv")
    db.mark_suggestion_dismissed(dismissed_id)

    default = db.list_suggestions()
    assert len(default) == 1
    assert default[0]["file_path"] == "C:/active.mkv"

    with_dismissed = db.list_suggestions(include_dismissed=True)
    assert len(with_dismissed) == 2


# ===========================================================================
# 23. Persistência entre duas instâncias diferentes
# ===========================================================================

def test_persistence_across_instances(db_path):
    """Dados gravados numa instância devem ser lidos por outra instância."""
    # Instância 1: gravar dados
    with StorageManagerDB(db_path) as db1:
        db1.set_setting("version", "1.0.0")
        db1.set_disk_role("C:", "SYSTEM")
        _insert_op(db1, source_path="C:/persist.txt", timestamp=5000.0)
        sid = db1.create_scan_session(started_at=5000.0, scan_mode="QUICK")
        db1.finish_scan_session(sid, elapsed_seconds=10.0, total_files_seen=99)
        db1.upsert_file_index(
            path="C:/persist.txt", disk_letter="C:",
            size_bytes=1024, mtime=5000.0, last_seen=5000.0,
        )
        _insert_sug(db1, scan_session_id=sid, file_path="C:/persist.txt")

    # Instância 2: ler e verificar
    with StorageManagerDB(db_path) as db2:
        assert db2.get_setting("version") == "1.0.0"
        assert db2.get_disk_role("C:") == "SYSTEM"

        ops = db2.list_operations()
        assert len(ops) == 1
        assert ops[0]["source_path"] == "C:/persist.txt"

        session = db2.get_scan_session(sid)
        assert session["elapsed_seconds"] == 10.0
        assert session["total_files_seen"] == 99

        fi = db2.get_file_index("C:/persist.txt")
        assert fi is not None
        assert fi["size_bytes"] == 1024

        sugs = db2.list_suggestions()
        assert len(sugs) == 1
        assert sugs[0]["file_path"] == "C:/persist.txt"


# ===========================================================================
# Extra: get_default_db_path retorna Path válido
# ===========================================================================

def test_get_default_db_path_returns_path():
    p = get_default_db_path()
    assert isinstance(p, type(p))  # Path
    assert p.suffix == ".db"
    assert "GestaoPC" in str(p) or ".gestaopc" in str(p)


# ===========================================================================
# Sprint 7.4 — get_file_index_batch + update_file_hashes_batch
# ===========================================================================

class TestGetFileIndexBatch:
    """Lookup em lote para o cache de hash."""

    def _seed_files(self, db, paths_with_size):
        # upsert_file_index gerencia sua própria transação — não usar `with db:`
        # aqui pois isso fecha a conexão do context manager externo.
        for path, size in paths_with_size:
            db.upsert_file_index(
                path=path,
                disk_letter=path[:2] if len(path) >= 2 else None,
                size_bytes=size,
                mtime=1000.0,
                last_seen=2000.0,
            )

    def test_empty_paths_returns_empty_dict(self, tmp_path):
        with StorageManagerDB(tmp_path / "t.db") as db:
            result = db.get_file_index_batch([])
        assert result == {}

    def test_single_path_lookup(self, tmp_path):
        with StorageManagerDB(tmp_path / "t.db") as db:
            self._seed_files(db, [("C:\\a.bin", 1000)])
            result = db.get_file_index_batch(["C:\\a.bin"])
        assert "C:\\a.bin" in result
        assert result["C:\\a.bin"]["size_bytes"] == 1000

    def test_multi_path_lookup(self, tmp_path):
        with StorageManagerDB(tmp_path / "t.db") as db:
            self._seed_files(db, [
                ("C:\\a.bin", 100),
                ("D:\\b.bin", 200),
                ("E:\\c.bin", 300),
            ])
            result = db.get_file_index_batch(
                ["C:\\a.bin", "D:\\b.bin", "E:\\c.bin"]
            )
        assert len(result) == 3
        assert result["C:\\a.bin"]["size_bytes"] == 100
        assert result["E:\\c.bin"]["size_bytes"] == 300

    def test_missing_paths_silently_omitted(self, tmp_path):
        with StorageManagerDB(tmp_path / "t.db") as db:
            self._seed_files(db, [("C:\\exists.bin", 100)])
            result = db.get_file_index_batch(
                ["C:\\exists.bin", "C:\\nope.bin"]
            )
        assert "C:\\exists.bin" in result
        assert "C:\\nope.bin" not in result

    def test_chunks_above_500_paths(self, tmp_path):
        """SQLite limita 999 placeholders; nosso chunking usa 500."""
        with StorageManagerDB(tmp_path / "t.db") as db:
            paths = [(f"C:\\file_{i}.bin", i * 10) for i in range(1500)]
            self._seed_files(db, paths)
            result = db.get_file_index_batch([p for p, _ in paths])
        assert len(result) == 1500


class TestUpdateFileHashesBatch:
    """Persistência em lote dos hashes recém-computados."""

    def test_empty_updates_returns_zero(self, tmp_path):
        with StorageManagerDB(tmp_path / "t.db") as db:
            assert db.update_file_hashes_batch([]) == 0

    def test_updates_partial_only(self, tmp_path):
        with StorageManagerDB(tmp_path / "t.db") as db:
            db.upsert_file_index(
                path="C:\\a.bin", disk_letter="C:", size_bytes=100,
                mtime=1.0, last_seen=2.0,
            )
            affected = db.update_file_hashes_batch(
                [("C:\\a.bin", "partial_h", None)]
            )
            assert affected == 1
            row = db.get_file_index("C:\\a.bin")
            assert row["partial_hash"] == "partial_h"
            assert row["full_hash"] is None  # Não tocou

    def test_updates_full_only_preserves_existing_partial(self, tmp_path):
        with StorageManagerDB(tmp_path / "t.db") as db:
            db.upsert_file_index(
                path="C:\\a.bin", disk_letter="C:", size_bytes=100,
                mtime=1.0, partial_hash="ph_existing", last_seen=2.0,
            )
            db.update_file_hashes_batch([("C:\\a.bin", None, "fh_new")])
            row = db.get_file_index("C:\\a.bin")
            assert row["partial_hash"] == "ph_existing", "Não deve ter sido apagado"
            assert row["full_hash"] == "fh_new"

    def test_updates_both_in_one_call(self, tmp_path):
        with StorageManagerDB(tmp_path / "t.db") as db:
            db.upsert_file_index(
                path="C:\\a.bin", disk_letter="C:", size_bytes=100,
                mtime=1.0, last_seen=2.0,
            )
            db.update_file_hashes_batch([("C:\\a.bin", "p", "f")])
            row = db.get_file_index("C:\\a.bin")
            assert row["partial_hash"] == "p"
            assert row["full_hash"] == "f"

    def test_missing_path_silently_skipped(self, tmp_path):
        """UPDATE em path inexistente afeta 0 linhas, sem crash."""
        with StorageManagerDB(tmp_path / "t.db") as db:
            affected = db.update_file_hashes_batch(
                [("C:\\never_inserted.bin", "p", "f")]
            )
            assert affected == 0

    def test_skips_entries_with_both_hashes_none(self, tmp_path):
        """Entry com partial=None e full=None não gera UPDATE."""
        with StorageManagerDB(tmp_path / "t.db") as db:
            db.upsert_file_index(
                path="C:\\a.bin", disk_letter="C:", size_bytes=100,
                mtime=1.0, partial_hash="keep", full_hash="keep_too",
                last_seen=2.0,
            )
            affected = db.update_file_hashes_batch(
                [("C:\\a.bin", None, None)]
            )
            assert affected == 0
            row = db.get_file_index("C:\\a.bin")
            assert row["partial_hash"] == "keep"
            assert row["full_hash"] == "keep_too"
