# Especificação de Módulo: Storage Manager (Gerenciador de Armazenamento)

## 1. Visão Geral e Objetivo
Este módulo é o núcleo de gerenciamento de armazenamento do "Gerenciador de PC". O objetivo é analisar todos os discos conectados ao sistema (Windows 11), identificar redundâncias (arquivos duplicados), analisar o uso de espaço e sugerir ou executar a realocação inteligente de arquivos com base no tipo de arquivo, tamanho e velocidade do disco (NVMe vs. SATA).

## 2. Contexto do Hardware Alvo
O sistema alvo possui a seguinte configuração de armazenamento (o código deve ser dinâmico, mas otimizado para este cenário):
- Disco Principal (C:): NVMe de 1TB (Alta Velocidade - Prioridade para SO, Jogos, Softwares pesados).
- Discos Secundários Internos: HDDs SATA de 2TB e 1TB (Velocidade Média - Prioridade para dados em massa, documentos, mídia).
- Discos Externos: 2x HDDs SATA de 3TB (Prioridade para Backup e Arquivo Morto).

## 3. Requisitos Funcionais (Core Logic)

### 3.1. Mapeamento de Discos
- O sistema deve usar `psutil` ou `wmi` para listar todas as partições lógicas montadas.
- Deve identificar a letra do disco, tipo de sistema de arquivos, espaço total, espaço usado e espaço livre.
- *Diferencial:* Tentar inferir o tipo de mídia (SSD/NVMe vs HDD) usando chamadas WMI no Windows (ex: `MSFT_PhysicalDisk` via módulo `wmi`).

### 3.2. Análise de Espaço e Categorização
- Varredura de diretórios para categorizar arquivos por tipo (Imagens, Vídeos, Documentos, Executáveis, Arquivos compactados).
- Identificar os "Top 50 Maiores Arquivos" e "Pastas que mais consomem espaço".

### 3.3. Detecção de Duplicatas
- Implementar um algoritmo eficiente em duas etapas para evitar uso excessivo de CPU:
  1. Agrupar arquivos com o **mesmo tamanho exato** (em bytes).
  2. Para arquivos com o mesmo tamanho, gerar e comparar o **Hash (SHA-256 ou MD5)** apenas de uma amostra (ex: primeiros 1MB e últimos 1MB) e, se bater, fazer o hash completo para confirmar a duplicata.

### 3.4. Motor de Regras de Realocação Inteligente (IA Simbólica/Regras)
- Criar uma função que recebe as informações de um arquivo e sugere uma nova localização baseada em regras:
  - **Regra 1:** Arquivos `.mp4`, `.mkv`, `.iso` maiores que 1GB no disco NVMe (C:) devem ser sugeridos para realocação nos discos SATA internos.
  - **Regra 2:** Arquivos duplicados devem sugerir a exclusão da cópia mais recente (ou da cópia fora da pasta raiz do usuário).
  - **Regra 3:** Se um disco estiver com mais de 90% de uso, sugerir movimentação em massa de arquivos de mídia para discos externos.

## 4. Requisitos de Interface Gráfica (GUI)
- **Framework:** PyQt6.
- **Estilo Visual:** Inspirado no ASUS AI Suite 3. Tema escuro (Dark Theme), paleta baseada em tons de preto (`#121212`), cinza escuro (`#1E1E1E`) e destaques em azul ciano (`#00A8FF`).
- **Componentes Necessários:**
  - Gráfico de barras ou pizza mostrando o uso de cada disco.
  - Lista (QTableWidget) exibindo arquivos duplicados encontrados, com checkboxes para selecionar quais deletar.
  - Painel de "Sugestões da IA" exibindo cards de realocação (Ex: "Mover 50GB de Vídeos de C: para D: para liberar espaço no NVMe").
  - Botões de ação com feedback visual (loading spinners durante varreduras).

## 5. Regras de Segurança e Antivírus (Integração Kaspersky)
- O código que realiza movimentação ou deleção de arquivos deve usar blocos `try...except` para capturar `PermissionError`.
- O Kaspersky pode bloquear arquivos temporariamente durante varreduras de fundo. O sistema não deve falhar (crash), deve apenas registrar um log (logging) de que o arquivo está bloqueado e pular para o próximo.
- Não manipular arquivos vitais do sistema (ignorar pastas como `C:\Windows`, `C:\Program Files`, `C:\ProgramData`). O foco da varredura deve ser as pastas de usuário e partições de armazenamento secundárias.

## 6. Critérios de Aceite (Para o Agente de IA)
1. O código gerado deve ser um módulo importável (`storage_manager.py`).
2. Deve conter uma classe PyQt6 separada para a interface visual.
3. Deve executar sem erros de sintaxe no Python 3.9+ no Windows 11.
4. O algoritmo de hash não deve travar a interface gráfica (deve rodar em uma `QThread` separada ou usar processamento assíncrono).