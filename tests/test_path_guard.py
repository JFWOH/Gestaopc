"""
Testes unitários para src.core.path_guard.

Cobre:
  - validate_path() — caminho vazio, relativo, absoluto seguro, protegido
  - assert_safe_path() — raise ValueError para caminhos inválidos
  - PROTECTED_PATH_PREFIXES e PROTECTED_FILENAMES
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.core.path_guard import (
    PROTECTED_FILENAMES,
    PROTECTED_PATH_PREFIXES,
    assert_safe_path,
    validate_path,
)


# ─────────────────────────────────────────────────────────────────────────────
# validate_path — entradas inválidas
# ─────────────────────────────────────────────────────────────────────────────

class TestValidatePathInvalid:
    def test_empty_string_rejected(self):
        ok, err = validate_path("")
        assert not ok
        assert err

    def test_whitespace_only_rejected(self):
        ok, err = validate_path("   ")
        assert not ok
        assert err

    def test_relative_path_rejected(self):
        ok, err = validate_path("Videos/filme.mkv")
        assert not ok
        assert "relativo" in err.lower()

    def test_dot_dot_relative_rejected(self):
        ok, err = validate_path("../../../Windows/System32/calc.exe")
        assert not ok
        assert "relativo" in err.lower()

    def test_windows_system32_rejected(self):
        ok, err = validate_path("C:\\Windows\\System32\\kernel32.dll")
        assert not ok
        assert err

    def test_windows_root_rejected(self):
        ok, err = validate_path("C:\\Windows\\notepad.exe")
        assert not ok
        assert err

    def test_program_files_rejected(self):
        ok, err = validate_path("C:\\Program Files\\SomeApp\\app.exe")
        assert not ok
        assert err

    def test_program_files_x86_rejected(self):
        ok, err = validate_path("C:\\Program Files (x86)\\app\\app.exe")
        assert not ok
        assert err

    def test_programdata_rejected(self):
        ok, err = validate_path("C:\\ProgramData\\Microsoft\\crypto.db")
        assert not ok
        assert err

    def test_pagefile_sys_rejected(self):
        ok, err = validate_path("C:\\pagefile.sys")
        assert not ok
        assert err

    def test_hiberfil_sys_rejected(self):
        ok, err = validate_path("C:\\hiberfil.sys")
        assert not ok
        assert err

    def test_swapfile_sys_rejected(self):
        ok, err = validate_path("C:\\swapfile.sys")
        assert not ok
        assert err

    def test_bootmgr_rejected(self):
        ok, err = validate_path("C:\\bootmgr")
        assert not ok
        assert err

    def test_system_volume_information_rejected(self):
        ok, err = validate_path("C:\\System Volume Information\\tracking.log")
        assert not ok
        assert err


# ─────────────────────────────────────────────────────────────────────────────
# validate_path — entradas válidas
# ─────────────────────────────────────────────────────────────────────────────

class TestValidatePathValid:
    def test_user_videos_accepted(self):
        ok, err = validate_path("C:\\Users\\joao\\Videos\\filme.mkv")
        assert ok
        assert err == ""

    def test_other_drive_accepted(self):
        ok, err = validate_path("D:\\Backup\\arquivo.zip")
        assert ok
        assert err == ""

    def test_deep_user_path_accepted(self):
        ok, err = validate_path("C:\\Users\\alice\\Documents\\projeto\\dados.csv")
        assert ok
        assert err == ""

    def test_external_drive_accepted(self):
        ok, err = validate_path("E:\\Media\\Filmes\\filme.mkv")
        assert ok
        assert err == ""

    def test_downloads_folder_accepted(self):
        ok, err = validate_path("C:\\Users\\bob\\Downloads\\installer.exe")
        assert ok
        assert err == ""

    def test_returns_tuple_of_two(self):
        result = validate_path("C:\\Users\\test\\file.txt")
        assert isinstance(result, tuple)
        assert len(result) == 2


# ─────────────────────────────────────────────────────────────────────────────
# assert_safe_path
# ─────────────────────────────────────────────────────────────────────────────

class TestAssertSafePath:
    def test_raises_for_relative_path(self):
        with pytest.raises(ValueError, match="relativo"):
            assert_safe_path("relative/path.txt")

    def test_raises_for_protected_path(self):
        with pytest.raises(ValueError):
            assert_safe_path("C:\\Windows\\explorer.exe")

    def test_raises_for_empty_path(self):
        with pytest.raises(ValueError):
            assert_safe_path("")

    def test_no_raise_for_valid_path(self):
        # Should not raise
        assert_safe_path("C:\\Users\\joao\\file.txt")

    def test_no_raise_for_other_drive(self):
        assert_safe_path("D:\\Videos\\movie.mp4")


# ─────────────────────────────────────────────────────────────────────────────
# Constantes de proteção
# ─────────────────────────────────────────────────────────────────────────────

class TestProtectionConstants:
    def test_protected_prefixes_is_non_empty(self):
        assert len(PROTECTED_PATH_PREFIXES) > 0

    def test_windows_in_protected_prefixes(self):
        assert any("WINDOWS" in p.upper() for p in PROTECTED_PATH_PREFIXES)

    def test_program_files_in_protected_prefixes(self):
        assert any("PROGRAM FILES" in p.upper() for p in PROTECTED_PATH_PREFIXES)

    def test_protected_filenames_is_frozenset(self):
        assert isinstance(PROTECTED_FILENAMES, frozenset)

    def test_pagefile_in_protected_filenames(self):
        assert "pagefile.sys" in PROTECTED_FILENAMES

    def test_hiberfil_in_protected_filenames(self):
        assert "hiberfil.sys" in PROTECTED_FILENAMES

    def test_protected_filenames_lowercase(self):
        # All entries should be lowercase for case-insensitive comparison
        for name in PROTECTED_FILENAMES:
            assert name == name.lower(), f"'{name}' deve ser lowercase"


# ─────────────────────────────────────────────────────────────────────────────
# validate_path — branch de OSError em Path.resolve()
# ─────────────────────────────────────────────────────────────────────────────

class TestValidatePathResolveError:
    """Cobre o branch L104-105: OSError/ValueError em p.resolve()."""

    def test_oserror_in_resolve_returns_invalid(self):
        with patch.object(Path, "resolve", side_effect=OSError("Device not ready")):
            ok, err = validate_path("C:\\some_absolute\\path.txt")
        assert not ok
        assert err

    def test_valueerror_in_resolve_returns_invalid(self):
        with patch.object(Path, "resolve", side_effect=ValueError("Invalid path")):
            ok, err = validate_path("C:\\other_absolute\\file.bin")
        assert not ok
        assert err
