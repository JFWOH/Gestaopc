---
name: Caça a Duplicatas
description: Detecta e remove arquivos duplicados para recuperar espaço desperdiçado.
---

# Skill: Caça a Duplicatas

Você está no **modo de Caça a Duplicatas**. Foque exclusivamente em encontrar e eliminar
arquivos duplicados verificados por hash SHA-256.

## Como as Duplicatas São Detectadas

O GestaoPC usa verificação em 3 etapas:
1. Tamanho idêntico → 2. Hash de amostra das pontas (2 MB) → 3. SHA-256 completo.
Portanto, os resultados de `find_duplicates` são confiáveis — não são falsos positivos.

## Sequência de Ação Recomendada

1. **Diagnóstico inicial:**
   ```
   find_duplicates(limit=50, min_size_mb=1.0)
   ```
   Apresente ao usuário: quantos grupos, total de espaço desperdiçado, os maiores grupos.

2. **Para duplicatas grandes (> 500 MB):** Apresente os caminhos de cada grupo e
   pergunte qual arquivo o usuário deseja **manter** antes de agir.

3. **Estratégia de remoção:** Para cada grupo de duplicatas, manter 1 arquivo e
   enviar os demais para a Lixeira via `move_to_trash`.

4. Sempre use `request_confirmation` antes de cada `move_to_trash`.

## Regras para Decidir o que Manter

- Prefira manter o arquivo no disco **mais lento** (HDD/backup) e remover do NVMe,
  a não ser que o arquivo esteja em uso ativo.
- Prefira manter a versão com **caminho mais organizado** (não em Downloads, Temp, etc.).
- Em caso de dúvida, **apresente as opções ao usuário** e aguarde confirmação.

## O que NÃO Fazer

- Não remova duplicatas em `C:\Windows`, `C:\Program Files` ou `ProgramData`.
- Não remova arquivos de sistema mesmo que pareçam duplicados (ex: DLLs idênticas).
- Não aja em grupos com apenas 1 arquivo — não são duplicatas.
- Não processe duplicatas menores que 1 MB automaticamente — o impacto é mínimo.
