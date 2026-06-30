# Auditoria de Eficiência e Segurança — GestaoPC Storage Manager

**Versão auditada:** 0.3.0 · **Data:** 2026-06-29 · **Tipo:** read-only (nenhum código alterado nesta auditoria)
**Método:** 3 auditorias paralelas independentes (eficiência/escalabilidade · segurança core · privacidade/dependências/robustez), lendo o código real com evidência `arquivo:linha`.

---

## Veredito geral

| Dimensão | Nota | Resumo |
|----------|------|--------|
| **Eficiência** | **7,0 / 10 — Boa, com bombas de escala** | Algoritmos corretos (dedup 3-etapas, cache de hash, threading sólido), mas gargalos reais de memória e tempo que estouram em discos grandes. |
| **Segurança** | **6,5 / 10 — Fundações fortes, brechas de alto impacto na superfície da IA** | SQL parametrizado, token binding (S-2), path guard central, rede mínima, telemetria privada. Porém a superfície LLM tem 3 furos ALTA. |
| **Privacidade/Robustez** | **8,5 / 10 — Exemplar** | Telemetria opt-in local sem PII, sem listener de rede, lifecycle de threads/DB correto, supply-chain disciplinado. |

> **Leitura de uma frase:** o app está bem arquitetado e é seguro para uso pessoal local; antes de expor a IA/MCP a entradas não confiáveis ou de escalar para discos de muitos TB, há um conjunto pequeno e bem definido de correções de alto retorno.

---

## Parte 1 — EFICIÊNCIA

### Achados

| # | Severidade | Achado | Evidência | Recomendação |
|---|-----------|--------|-----------|--------------|
| E1 | **ALTA** | Dupla travessia da árvore por disco — cada arquivo é `stat()`-ado **2×** (uma p/ arquivos, outra p/ pastas) | `workers.py:162-208` (chama `top_largest_files` e depois `top_largest_dirs` sobre os mesmos alvos) | Unificar numa única travessia que acumula top-N de arquivos **e** tamanho por pasta no mesmo passo |
| E2 | **ALTA** | `top_largest_files` materializa **todos** os arquivos antes de cortar top-50 → pico de memória ∝ total varrido | `scanner.py:271-303` (`entries.append(...)` para tudo, depois `sort()` + `[:n]`) | `heapq.nlargest(n, ...)` ou min-heap de tamanho N — memória O(N), tempo O(M log N) |
| E3 | **ALTA** | SHA-256 lê em blocos de **8 KB** → ~393 mil iterações Python p/ arquivo de 3 GB; é a maior alavanca dos ~73 min da Etapa 3 | `config.py:50` `HASH_FULL_CHUNK_SIZE=8192`; `analyzer.py:293-298` | Subir p/ 1 MB (≈128× menos iterações) ou usar `hashlib.file_digest` (3.11+); 2-5× mais rápido |
| E4 | **ALTA** | `file_index` só persiste o **top-50 global** → IA/MCP enxergam só 50 arquivos; cega para o disco real | `workers.py:216, 248, 314`; tools em `ai_toolbelt.py:356, 455` | Desacoplar "top exibido" de "índice persistido"; indexar todos acima de um limiar + grupos de duplicatas |
| E5 | MÉDIA | Detecção de duplicatas só vê o top-N por alvo → falsos negativos (duplicatas médias/pequenas nunca entram) | `workers.py:168-170` + `analyzer.py:131,160` | Rodar a Etapa 1 (agrupar por tamanho, barato) sobre **todos** os arquivos varridos |
| E6 | MÉDIA | `_get_system_context()` roda no **thread da UI** e dispara PowerShell de até 15s → janela congela na 1ª mensagem do chat | `assistant_tab.py:589-593, 478`; `scanner.py:460-466` | Construir o contexto no QThread; cachear `_detect_media_types` (tipo de mídia não muda) |
| E7 | MÉDIA¹ | **Zero índices secundários** no SQLite (`CREATE INDEX` inexistente) | `storage_db.py:87-157`; queries `:749, 768` | Índices em `file_index(size_bytes, full_hash, disk_letter, category)`, `operation_history(timestamp)` |
| E8 | BAIXA² | N+1 de upserts (1 commit/fsync por arquivo, 2× por scan); `update_file_hashes_batch` existe mas não é usado | `workers.py:352-365`; `storage_db.py:505, 562` | Uma transação por lote (`executemany`); `PRAGMA synchronous=NORMAL` em WAL |

¹ Baixa hoje (índice tem ~50 linhas) → vira **ALTA** assim que E4 for corrigido. &nbsp;² Baixa hoje → MÉDIA em escala.

### Pontos fortes de eficiência
1. **Pipeline de duplicatas 3-etapas** (tamanho → hash parcial → SHA-256) — poda os casos baratos primeiro; algoritmicamente correto.
2. **Hash parcial lê só head+tail de 1 MB** com short-circuit p/ arquivos ≤2 MB.
3. **Cache de hash com validação size+mtime** — re-scans caem de ~73 min para segundos quando nada mudou.
4. **`_get_scan_targets` + poda de `SYSTEM_EXCLUDED_DIRS`** — evita varrer raízes inteiras e árvores de SO.
5. **Concorrência sólida:** conexão SQLite por thread, WAL, `partial_result` (persistência antecipada — corrigido nesta sessão), chunking de 500 placeholders em `get_file_index_batch`.

---

## Parte 2 — SEGURANÇA (core)

> **Contexto de risco:** o app **move e deleta** arquivos do usuário e expõe ações executivas a uma **IA local (Ollama)** e a **clientes MCP externos**. O modelo de ameaça central é: IA alucinada, *prompt injection* ou cliente MCP malicioso destruindo/movendo dados.

### Confirmação do RECON anterior
**S-1** (path guard universal), **S-2** (token args binding SHA-256) e **S-4** (validação de destino) estão **de fato implementados** e foram confirmados no código (`executor.py:147,211`; `ai_toolbelt.py:101-118,257-275,729-732,862`).

### Achados novos

| # | Severidade | Achado | Evidência | Mitigação |
|---|-----------|--------|-----------|-----------|
| S5 | **ALTA** | O "confirmation token" **não é um gate humano** — `request_confirmation` é só mais uma tool que o próprio LLM chama; ele se auto-autoriza no mesmo loop | `ai_toolbelt.py:572-610`; `assistant_tab.py:122-148` | Emitir o token **só** via ação de UI (diálogo humano mostrando risco), nunca por tool que o LLM invoque sozinho |
| S6 | **ALTA** | `_execute_tool` faz `getattr(tb, name)` com `name` vindo do LLM, **sem whitelist** → modelo pode chamar `_reset_rate_limiter`/`_reset_token_store` e desligar os controles | `assistant_tab.py:60-67` | Validar `name` contra a lista de `get_tool_schemas()`; rejeitar prefixo `_` ou fora da lista |
| S7 | **ALTA**³ | Bypass do path guard via prefixo `\\?\` e caminhos **UNC** (`\\servidor\share`) — comparação `startswith("C:\\WINDOWS")` não normaliza prefixo estendido | `path_guard.py:103-111` | Remover `\\?\`/`\\?\UNC\` antes de comparar; comparar por **componentes** (`PurePath.parts`); tratar UNC |
| S8 | MÉDIA | Token store (`dict`) e rate limiter (`list`) **não são thread-safe** → sob MCP concorrente, token one-shot usado 2× e rate-limit furado (TOCTOU) | `ai_toolbelt.py:90,132,238-276,135-152` | `threading.Lock`; consumir token e reservar slot de rate-limit **atomicamente** no gate |
| S9 | MÉDIA | `ai_source` é **forjável** pelo LLM no caminho Ollama → ação da IA gravada no histórico como se fosse do usuário (`"ui"`) | `ai_toolbelt.py:645,707,...`; `assistant_tab.py:67` | Remover `ai_source` dos args do modelo e injetar `ai:ollama` à força |
| S10 | MÉDIA | Sem `send2trash`, "Lixeira" vira **deleção permanente silenciosa** — contradiz a descrição "reversível" que a IA usa p/ avaliar risco | `ai_toolbelt.py:670-677,827-832`; `mcp_server.py:206-210` | Falhar a ação se `send2trash` ausente, ou refletir `used_trash=False` no risco e exigir confirmação reforçada |
| S11 | MÉDIA | Modelo **denylist**: só dirs de SO em `C:` são bloqueados → `C:\Users`, discos `D:/E:`, `D:\Windows` ficam desprotegidos | `path_guard.py:37-46` | Complementar com **allowlist** de raízes operáveis; cobrir `*:\Windows`, `*:\Program Files*` em qualquer letra |
| S12 | MÉDIA/BAIXA | TOCTOU: valida o caminho **resolvido**, age sobre o caminho **bruto** (symlink/junction trocável entre validação e ação) | `path_guard.py:103`; `ai_toolbelt.py:734,751`; `executor.py:155` | Operar sobre o caminho **canônico** devolvido pela validação |
| S13 | BAIXA | `undo_last_operation` sem proteção contra sobrescrita do destino (sem sufixo único como `move_file`) | `ai_toolbelt.py:964-965` | Aplicar a mesma desambiguação por sufixo, ou recusar se o destino existir |

³ ALTA com ressalva: deletar em `C:\Windows` ainda exige permissão NTFS; o impacto real é maior em UNC/rede e dirs sensíveis sem admin.

### Pontos fortes de segurança
1. **SQL 100% parametrizado** — sem injeção apesar de args virem do LLM (`storage_db.py`).
2. **Token forte** — `secrets.token_hex(16)` (128 bits), one-shot, TTL 60s, **args binding SHA-256** (S-2).
3. **Path guard centralizado e reusado** — um único `validate_path` cobre GUI e IA, revalida caminhos lidos do DB no undo/apply.
4. **Deleção reversível por padrão** + rate-limit (3/min) + `max_iterations=5` no loop agente.
5. **Superfície de rede mínima** — MCP só em `stdio` (sem socket); erros ao cliente externo são sanitizados; MCP fixa `ai_source` corretamente (o defeito S6/S9 é só no caminho Ollama).

---

## Parte 3 — PRIVACIDADE, DEPENDÊNCIAS, ROBUSTEZ

| # | Severidade | Achado | Recomendação |
|---|-----------|--------|--------------|
| P1 | MÉDIA | Caminhos absolutos vão ao modelo Ollama via tool results (nome de usuário/projetos). Local hoje (loopback fixo), mas sem allowlist se o host mudar | Avisar se `OLLAMA_DEFAULT_HOST` não for loopback; minimizar caminhos (basename) nos results |
| P2 | MÉDIA | Sem lockfile com hashes / `pip-audit` → builds não reproduzíveis, sem detecção de vuln transitiva | Gerar lockfile com hashes p/ release; `pip-audit` no CI |
| P3 | MÉDIA | Caminhos absolutos em logs INFO (`executor.py:173,230`). Mitigado: sem FileHandler (só stderr) e `console=False` no build → não persiste em disco | Reduzir p/ basename em INFO se um FileHandler for adicionado |
| P4 | BAIXA | `except: pass` residuais (telemetry/UI) — majoritariamente justificados | Trocar por `logger.debug(exc_info=True)` |

### Pontos fortes (privacidade/robustez)
1. **Telemetria modelo de privacidade:** opt-in real, 100% local (`%LOCALAPPDATA%\...jsonl`), zero PII, **zero rede**.
2. **Superfície de rede mínima:** MCP via stdio, Ollama loopback, **nada em `0.0.0.0`**, sem FastAPI/OPDS.
3. **Supply-chain disciplinado:** pins de teto em todas as deps, transitivas declaradas, LGPL documentada + onedir/UPX-off.
4. **Lifecycle correto:** threads/DB encerrados no `closeEvent`; scanner resiliente a AV/disco-removido/PowerShell-ausente; migrações idempotentes (WAL + FK).
5. **Guardrails de IA:** confirmação por token, rate-limit, batch cap (50) contra deleção em massa.

---

## Roadmap de correção priorizado

**Sprint de Hardening (alto retorno, baixo custo) — recomendado antes de qualquer exposição não-local:**
1. **S6** — Whitelist de nomes de tool em `_execute_tool` (bloqueia `getattr` arbitrário). *Barato, alto impacto.*
2. **S9 + S10** — Forçar `ai_source`; tratar `send2trash` ausente como falha, não deleção permanente.
3. **S7** — Normalizar `\\?\`/UNC e comparar path guard por componentes (corrige também o E-falso-positivo de fronteira).
4. **S8** — `Lock` no token store e rate limiter; reservar slot no gate.
5. **S5** — Confirmação humana real fora da banda da IA para ações executivas.

**Sprint de Escala (quando for indexar discos grandes):**
6. **E2** (heap em `top_largest_files`) + **E1** (travessia única) + **E3** (chunk 1 MB) — os três maiores ganhos de tempo/memória.
7. **E4 + E7** — persistir índice completo **junto** com os índices SQLite (um depende do outro).

**Polimento:**
8. E6 (contexto da IA fora do thread da UI), E5, E8, P1-P4.

---

*Auditoria gerada por 3 agentes independentes sobre o código real; achados ALTA/Crítica merecem verificação pontual antes da correção. Nenhum arquivo foi alterado nesta auditoria.*
