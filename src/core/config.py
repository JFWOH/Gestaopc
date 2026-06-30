"""
Configuração centralizada do GestaoPC — Sprint 7.6.

Todos os valores constantes (magic numbers) do projeto vivem aqui. Antes
estavam espalhados por scanner/analyzer/executor/workers/etc., dificultando
auditoria e ajuste.

Convenções:
  - Constantes que afetam comportamento de produção: prefixo do domínio
    (SCAN_*, HASH_*, AI_*, OLLAMA_*, WORKER_*, EXECUTOR_*, LOG_*).
  - Tipos explícitos em todas as constantes para suportar `mypy --strict`.
  - Sem `Final[T]` — usar comentário se necessário; mantém compatibilidade
    com o Protocol existente onde alguns testes substituem valores via patch
    (ex.: HASH_SAMPLE_SIZE em test_analyzer.py).

Configurações dinâmicas (preferências do usuário) NÃO ficam aqui — vão para
``app_settings`` no SQLite via :class:`StorageManagerDB`.
"""

from __future__ import annotations


# ============================================================================
# Scanner / Storage
# ============================================================================

# Partições menores que isto são ignoradas pela varredura (ex.: System Reserved).
SCAN_MIN_PARTITION_BYTES: int = 100 * 1024 * 1024  # 100 MB

# Quantos arquivos retornar no top por disco antes do merge global.
SCAN_TOP_FILES_PER_DISK: int = 50

# Quantas pastas retornar no top por disco.
SCAN_TOP_DIRS_PER_DISK: int = 20

# Profundidade máxima de recursão em top_largest_dirs (limita scan time).
SCAN_DIR_MAX_DEPTH: int = 2


# ============================================================================
# Hash / Duplicate Detection
# ============================================================================

# Tamanho da amostra (head + tail) usado no hash parcial SHA-256.
# Arquivos > 2 × HASH_SAMPLE_SIZE têm head e tail concatenados; menores têm
# o conteúdo inteiro hasheado uma única vez.
HASH_SAMPLE_SIZE: int = 1024 * 1024  # 1 MB

# Tamanho do chunk lido em loop para hash completo (Etapa 3).
# E3 (Sprint de Escala): 1 MB em vez de 8 KB — reduz ~128× as iterações Python
# e syscalls de read() ao hashear arquivos grandes (ex.: ISO de 3 GB: ~3 mil
# leituras em vez de ~393 mil), principal alavanca de tempo da detecção de
# duplicatas. Custo de RAM (1 MB por hash em andamento) é irrelevante.
HASH_FULL_CHUNK_SIZE: int = 1024 * 1024  # 1 MB

# Tolerância em segundos ao comparar mtime do filesystem com o cacheado no DB.
# NTFS resolve em 100ns mas Python/pytest introduzem jitter de até 1s.
HASH_CACHE_MTIME_TOLERANCE: float = 1.0


# ============================================================================
# Executor / File Operations
# ============================================================================

# Limite de operações por chamada do FileActionWorker (proteção contra
# IA enviando deletes massivos por engano).
EXECUTOR_MAX_BATCH_SIZE: int = 50


# ============================================================================
# AI Toolbelt
# ============================================================================

# Operações executivas por minuto permitidas pelo rate limiter.
AI_MAX_EXEC_PER_MINUTE: int = 3

# TTL do token de confirmação one-shot, em segundos.
AI_TOKEN_TTL_SECONDS: int = 60


# ============================================================================
# Ollama Client
# ============================================================================

# Host padrão do servidor Ollama local.
OLLAMA_DEFAULT_HOST: str = "http://localhost:11434"


# ============================================================================
# Log Bridge / Status Bar
# ============================================================================

# Tamanho máximo de uma mensagem repassada do logger para a status bar.
LOG_BRIDGE_MAX_MESSAGE_LENGTH: int = 200


# ============================================================================
# GUI Workers — timeouts (em milissegundos)
# ============================================================================

# Timeout para QThread.wait() no closeEvent — operação cooperativa.
WORKER_QUIT_TIMEOUT_MS: int = 3000

# Timeout curto para cleanup quando o worker já sinalizou finished_response.
WORKER_CLEANUP_TIMEOUT_MS: int = 500

# Timeout intermediário usado em _send_message (defensivo, antes de novo worker).
WORKER_RESTART_TIMEOUT_MS: int = 2000

# Timeout para fallback terminate() quando wait() falha.
WORKER_TERMINATE_TIMEOUT_MS: int = 1000
