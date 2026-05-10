# Third-Party Notices

GestaoPC Storage Manager é distribuído sob a licença **MIT** (ver `LICENSE`
ou `pyproject.toml`). Esta página lista as bibliotecas de terceiros utilizadas
e os termos de licença que se aplicam a cada uma.

A distribuição binária do GestaoPC inclui (ou pressupõe a instalação via pip)
os componentes abaixo. Cada um permanece sob sua licença original; nada na
licença MIT do GestaoPC altera ou substitui esses termos.

---

## Qt for Python (PySide6) — LGPL v3

GestaoPC vincula-se dinamicamente ao **PySide6**, distribuído pela The Qt
Company sob a **GNU Lesser General Public License v3 (LGPL-3.0)**. O Qt
framework subjacente também é distribuído sob LGPL-3.0.

**Texto completo:** https://www.gnu.org/licenses/lgpl-3.0.html

### Conformidade LGPL aplicável a esta distribuição

A LGPL v3 permite que software proprietário ou sob outras licenças (como o
GestaoPC sob MIT) faça uso da biblioteca, desde que o usuário final possa
substituir a versão da biblioteca utilizada. Os mecanismos abaixo garantem
essa conformidade:

1. **Substituição via pip**: Se você instalou o GestaoPC via `pip install`
   ou a partir do código-fonte, o PySide6 é uma dependência separada e pode
   ser atualizada a qualquer momento via:
   ```
   pip install --upgrade "PySide6>=6.6,<7.0"
   ```

2. **Substituição em distribuições empacotadas (PyInstaller / similar)**:
   Quando o GestaoPC for empacotado como executável, as DLLs do PySide6/Qt
   serão distribuídas como arquivos separados (não embedded), permitindo
   sua substituição manual. As instruções específicas de substituição estarão
   no arquivo `README.md` da distribuição binária correspondente.

3. **Não modificamos PySide6 nem Qt**: O GestaoPC consome essas bibliotecas
   apenas via suas APIs públicas, sem patches ou builds customizadas.

4. **Código-fonte do GestaoPC**: Disponibilizado sob a licença MIT no
   repositório do projeto. A licença MIT é compatível com o uso da LGPL
   por linkagem dinâmica.

### Por que PySide6 e não PyQt6?

A versão 0.3.x do GestaoPC migrou de PyQt6 (GPL/Commercial) para PySide6
(LGPL) no Sprint 7.3.1 para preservar a licença MIT do projeto. PyQt6
exigiria que distribuições gratuitas adotassem GPL, criando incompatibilidade
com terceiros que queiram embarcar o GestaoPC em produtos não-GPL.

---

## Outras bibliotecas

| Biblioteca | Licença | Propósito |
|---|---|---|
| psutil | BSD-3-Clause | Inventário de partições e disco |
| send2trash | BSD-3-Clause | Envio de arquivos para a Lixeira do Windows |
| mcp (Model Context Protocol) | MIT | Servidor de tools para clientes LLM externos |
| anyio, httpx, pydantic | MIT/Apache-2.0 | Dependências transitivas do MCP |
| pytest, pytest-cov, ruff | MIT | Apenas em desenvolvimento; não distribuídas |

Todas essas licenças são compatíveis com a licença MIT do GestaoPC e com a
LGPL do PySide6.

---

## Reportar problemas de licenciamento

Se você identificar qualquer uso de biblioteca que viole os termos acima ou
que não esteja documentado, abra uma issue no repositório do projeto.
