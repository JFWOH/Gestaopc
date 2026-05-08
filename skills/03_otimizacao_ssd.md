---
name: Otimização de SSD/NVMe
description: Libera espaço em discos rápidos movendo arquivos grandes para HDDs de backup.
---

# Skill: Otimização de SSD/NVMe

Você está no **modo de Otimização de SSD/NVMe**. O objetivo é maximizar espaço livre
nos discos rápidos (NVMe/SSD) movendo conteúdo pesado para HDDs lentos ou externos.

## Filosofia de Otimização

- **Discos NVMe/SSD** são valiosos pela velocidade. Apenas arquivos que se beneficiam
  de acesso rápido (jogos ativos, projetos em uso, sistema operacional) devem ficar neles.
- **Arquivos de arquivo, backups e mídia** raramente precisam de velocidade e devem
  residir em HDDs ou discos externos.

## Sequência de Ação Recomendada

1. Chame `list_partitions` para mapear todos os discos e identificar quais são NVMe/SSD
   com pouco espaço livre (menos de 20% livre).

2. Para cada NVMe/SSD com pouco espaço, use `find_top_files(drive_letter="X", limit=30)`
   para identificar os maiores arquivos.

3. Chame `list_suggestions` — o SmartRulesEngine pode já ter detectado arquivos mal alocados.

4. Classifique candidatos à migração:
   - Vídeos e imagens grandes → mover para disco `media` ou `backup`
   - Backups e archives → mover para disco `backup` ou `external`
   - Instaladores usados → enviar para Lixeira

5. Para mover arquivos: `request_confirmation` → `move_file(src, dst, token)`.
   Para sugestões prontas: `request_confirmation` → `apply_suggestion(id, token)`.

## Como Definir Papéis de Disco

Se o usuário não tiver papéis de disco configurados, sugira:
- Disco C: (NVMe/SSD pequeno) → `set_disk_role("C", "primary", token)`
- Disco D: (HDD grande) → `set_disk_role("D", "media", token)` ou `"backup"`

Use `request_confirmation` antes de `set_disk_role`.

## Meta de Espaço Livre

Recomende manter pelo menos **20% livre** em SSDs/NVMes para desempenho ótimo.
