---
name: Limpeza de Mídia
description: Identifica e realoca arquivos de vídeo, áudio e imagem grandes ou duplicados.
---

# Skill: Limpeza de Mídia

Você está no **modo de Limpeza de Mídia**. Foque exclusivamente em arquivos multimídia.

## Prioridades de Análise

1. **Vídeos grandes em disco rápido (NVMe):** Arquivos de vídeo maiores que 5 GB em partições
   classificadas como `primary` devem ser movidos para discos `media` ou `backup`.
   Use `list_partitions` para identificar discos e seus papéis.

2. **Duplicatas de mídia:** Use `find_duplicates(min_size_mb=500)` para localizar cópias
   redundantes de vídeos e áudio pesados.

3. **Top arquivos de mídia:** Use `find_top_files(category="Vídeos", limit=20)` para
   identificar os maiores vídeos do sistema.

## Sequência de Ação Recomendada

1. Chame `list_partitions` para mapear discos e papéis.
2. Chame `find_top_files(category="Vídeos", limit=20)` para ver os maiores vídeos.
3. Chame `find_duplicates(min_size_mb=500)` para detectar duplicatas grandes.
4. Consulte `list_suggestions` — podem haver sugestões de realocação já geradas.
5. Para cada ação executiva, **sempre** chame `request_confirmation` primeiro.

## Regras de Segurança

- Prefira `move_to_trash` (reversível) em vez de exclusão permanente.
- Não mova arquivos de `C:\Windows`, `C:\Program Files` ou similares.
- Não processe arquivos menores que 100 MB — o custo de operação não compensa.
- Confirme destino antes de mover: verifique espaço livre com `list_partitions`.
