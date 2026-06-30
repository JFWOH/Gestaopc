# Testes Práticos — Checklist de Aceitação

Roteiro manual para validar as funcionalidades na máquina real **após a fase de
desenvolvimento** (complementa os 581 testes automatizados, que não exercem
hardware/UI/Ollama reais). Marque cada item ao confirmar.

> Pré-requisitos: `pip install -e .` num venv com PySide6; Ollama rodando para os
> testes de IA (`ollama run llama3`).

## 1. Inicialização e Varredura
- [ ] `python run_gui.py` abre a janela sem erros no console.
- [ ] `python run_gui.py --auto-scan` inicia a varredura sozinho ~1s após abrir.
- [ ] Durante a varredura: o painel por disco mostra ○→⟳→✓ e o cronômetro corre.
- [ ] A status bar exibe mensagens de progresso (não fica em silêncio nos minutos
      de hash SHA-256).
- [ ] Ao final, a aba **Visão Geral** mostra cada disco com tipo correto
      (NVMe/SSD/HDD) e o donut chart de uso.

## 2. Top Arquivos / Pastas
- [ ] **Top Arquivos**: lista os maiores arquivos; filtro por categoria funciona
      (incl. **Áudio** e **Modelos IA** — `.gguf`/`.mp3` não caem em "Outros").
- [ ] **Top Pastas**: uma pasta com muito conteúdo em subníveis profundos
      (ex.: `node_modules`, `models/`) aparece com o tamanho **real** (não 0/subcontado).

## 3. Duplicatas
- [ ] **Duplicatas** lista grupos reais (crie 2-3 cópias idênticas para testar).
- [ ] Selecionar e enviar uma cópia para a Lixeira move o arquivo para a Lixeira
      do Windows (recuperável).

## 4. Motor de Regras (Sugestões)
- [ ] **Sugestões** mostra cards quando há mídia pesada em NVMe / disco >90%.
- [ ] Nenhuma sugestão propõe destino **sem espaço suficiente** nem mover para o
      **mesmo disco** de origem (validação da Fase RECON 6.2).

## 5. Executor + Undo + Histórico
- [ ] Mover um arquivo de teste entre discos pela UI funciona.
- [ ] Tentar mover/deletar algo em pasta protegida (`C:\Windows`, `Program Files`)
      é **bloqueado** com mensagem clara.
- [ ] **Histórico** registra a operação; **Desfazer** reverte e atualiza a lista.

## 6. Assistente IA (Ollama)
- [ ] Aba **Assistente IA** lista os modelos do Ollama; se o servidor estiver
      desligado, exibe aviso (não trava).
- [ ] Pergunta de leitura (ex.: "quais meus maiores arquivos?") retorna resposta
      usando tool-calling (indicadores de tool aparecem).
- [ ] Ação executiva (ex.: "mova X para a lixeira") **só executa após confirmação**
      (token one-shot); reusar/forjar argumentos é recusado.
- [ ] Trocar a **Skill** no ComboBox muda o comportamento do assistente.
- [ ] Fechar a aba/app durante uma resposta não deixa thread órfã nem trava.

## 7. Servidor MCP
- [ ] `python -m scripts.mcp_server` sobe sem erro.
- [ ] Conectado a um cliente (ex.: Claude Desktop), as 13 tools aparecem e uma
      leitura (ex.: `list_partitions`) retorna dados; ações ficam auditadas como
      `ai:mcp` no histórico.

## 8. Degradação graciosa (Fase A2)
- [ ] Num ambiente sem PowerShell/`Get-PhysicalDisk` (ou simulado), a varredura
      ainda completa, os discos ficam "Desconhecido" e a status bar **avisa** que
      a detecção de tipo de disco está indisponível.

## 9. Backend de IA injetável (Fase C)
- [ ] Com o Ollama no padrão, o assistente funciona normalmente (default
      `OllamaClient` preservado). *(Troca de backend é ponto de extensão, sem UI.)*

## 10. Build de Release / Distribuição (Fase B)
- [ ] `pip install -e ".[packaging]"` + `python scripts/build_release.py` gera
      `dist/GestaoPC/`.
- [ ] `dist/GestaoPC/GestaoPC.exe` abre a GUI numa máquina **sem Python**.
- [ ] As DLLs do Qt estão **soltas** em `_internal/PySide6/` (substituíveis — LGPL),
      e `README.md`/`LICENSES/` acompanham a pasta.

## 11. Qualidade / CI
- [ ] `pytest -m unit -q` roda rápido (só unitários); `pytest -m integration -q`
      roda o resto; juntos = suíte completa.
- [ ] `ruff check .` e `mypy src/` passam limpos.
