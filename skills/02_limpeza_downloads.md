---
name: Limpeza de Downloads
description: Analisa e limpa pastas de download, removendo instaladores antigos e arquivos temporários.
---

# Skill: Limpeza de Downloads

Você está no **modo de Limpeza de Downloads**. Foque na pasta Downloads e em instaladores obsoletos.

## O que Procurar

1. **Instaladores antigos:** Arquivos `.exe`, `.msi`, `.iso` na pasta Downloads que provavelmente
   já foram utilizados e não são mais necessários.

2. **Arquivos compactados redundantes:** `.zip`, `.rar`, `.7z` cujo conteúdo já foi extraído
   (verificar se há pasta de mesmo nome próxima ao arquivo).

3. **Downloads duplicados:** Mesmos arquivos baixados múltiplas vezes com sufixos como
   `(1)`, `(2)`, `Copy of`, etc.

## Sequência de Ação Recomendada

1. Use `find_top_files(category="Executáveis", limit=30)` para localizar instaladores grandes.
2. Use `find_top_files(category="Compactados", limit=20)` para archives grandes.
3. Use `find_duplicates(min_size_mb=50)` para detectar downloads duplicados.
4. Apresente ao usuário uma lista dos candidatos a remoção antes de agir.
5. Para cada remoção, use `request_confirmation` e depois `move_to_trash`.

## Regras de Segurança

- **Nunca** remova automaticamente sem apresentar a lista ao usuário primeiro.
- Prefira `move_to_trash` — o usuário pode recuperar da Lixeira se necessário.
- Não assuma que um instalador `.exe` pode ser removido sem confirmar com o usuário.
- Verifique se arquivos `.iso` não são de backup de sistema antes de sugerir remoção.
