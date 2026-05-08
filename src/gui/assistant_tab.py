"""
Aba do Assistente IA Local — integração com Ollama via tool-calling.

Fluxo de interação:
  1. Usuário envia mensagem.
  2. OllamaAgentWorker (QThread) executa o loop agente:
       a. Envia mensagens + tools ao Ollama (chat_with_tools).
       b. Se modelo retorna tool_calls: executa via ai_toolbelt, adiciona resultado e itera.
       c. Se modelo retorna texto: sinaliza finished_response.
  3. Indicadores visuais mostram quais tools foram chamadas durante a iteração.
  4. Resposta final é exibida no chat.

Contexto injetado automaticamente (via _get_system_context):
  - Estado de todas as partições (live via scanner)
  - Sugestões pendentes do SmartRulesEngine (do DB)
  - Resumo de duplicatas grandes (do DB)
  - Últimas 5 operações do histórico (do DB)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit,
    QPushButton, QComboBox, QLabel, QFrame
)
from PyQt6.QtGui import QTextCursor

import src.core.ai_toolbelt as tb
from src.core.ollama_client import OllamaClient
from src.core.storage_db import StorageManagerDB, get_default_db_path
from src.gui.styles import Colors

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Executor de tools (bridge ai_toolbelt → Ollama agent)
# ─────────────────────────────────────────────────────────────────────────────

def _execute_tool(name: str, args: dict) -> object:
    """
    Executa uma tool do ai_toolbelt por nome.

    Ações executivas passam ai_source='ai:ollama' automaticamente (é o default
    em todas as funções executivas do toolbelt).
    """
    fn = getattr(tb, name, None)
    if fn is None:
        return {
            "error": "TOOL_NOT_FOUND",
            "message": f"Tool '{name}' não encontrada no ai_toolbelt.",
        }
    try:
        return fn(**args)
    except TypeError as exc:
        return {"error": "ARG_ERROR", "message": f"Argumentos inválidos para '{name}': {exc}"}
    except Exception as exc:
        logger.exception("Erro ao executar tool '%s'", name)
        return {"error": "EXECUTOR_ERROR", "message": str(exc)}


def _human_size(size_bytes: int) -> str:
    """Converte bytes para string legível."""
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / (1024 ** 3):.1f} GB"
    if size_bytes >= 1024 ** 2:
        return f"{size_bytes / (1024 ** 2):.0f} MB"
    return f"{size_bytes / 1024:.0f} KB"


# ─────────────────────────────────────────────────────────────────────────────
# Workers (QThreads)
# ─────────────────────────────────────────────────────────────────────────────

class OllamaChatWorker(QThread):
    """Thread para chat simples com streaming (fallback sem tool-calling)."""

    token_received = pyqtSignal(str)
    finished_response = pyqtSignal()

    def __init__(self, model: str, messages: list[dict], parent=None):
        super().__init__(parent)
        self.model = model
        self.messages = messages
        self._client = OllamaClient()

    def run(self):
        for token in self._client.chat_stream(self.model, self.messages):
            self.token_received.emit(token)
        self.finished_response.emit()


class OllamaAgentWorker(QThread):
    """
    Thread para o loop agente com tool-calling.

    Emite eventos granulares para que a UI atualize indicadores em tempo real.
    """

    # Sinaliza início de chamada de tool: (nome_da_tool, resumo_dos_args)
    tool_call_started = pyqtSignal(str, str)
    # Sinaliza conclusão de chamada: (nome_da_tool, resumo_do_resultado)
    tool_call_finished = pyqtSignal(str, str)
    # Texto final do modelo (resposta completa, não streaming)
    text_received = pyqtSignal(str)
    # Erro no loop agente
    error_occurred = pyqtSignal(str)
    # Loop encerrado (com texto ou com erro)
    finished_response = pyqtSignal()

    def __init__(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict],
        parent=None,
    ):
        super().__init__(parent)
        self.model = model
        self.messages = messages
        self.tools = tools
        self._client = OllamaClient()

    def run(self):
        for event in self._client.chat_with_tools(
            self.model, self.messages, self.tools, _execute_tool
        ):
            etype = event.get("type")

            if etype == "tool_call":
                name = event["name"]
                args = event.get("args", {})
                # Resumo curto dos argumentos para exibição
                args_parts = [f"{k}={v!r}" for k, v in args.items()] if args else []
                args_summary = ", ".join(args_parts)[:120]
                self.tool_call_started.emit(name, args_summary)

            elif etype == "tool_result":
                name = event["name"]
                result = event.get("result", {})
                result_str = json.dumps(result, ensure_ascii=False, default=str)
                self.tool_call_finished.emit(name, result_str[:250])

            elif etype == "text":
                self.text_received.emit(event.get("content", ""))

            elif etype == "error":
                self.error_occurred.emit(event.get("message", "Erro desconhecido."))

        self.finished_response.emit()


# ─────────────────────────────────────────────────────────────────────────────
# Widget principal da aba
# ─────────────────────────────────────────────────────────────────────────────

class AssistantTab(QWidget):
    """
    Aba do Assistente IA local com suporte a tool-calling via Ollama.

    Usa OllamaAgentWorker por padrão. Se o modelo não suportar tool-calling,
    o loop encerra naturalmente com uma resposta de texto.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = OllamaClient()
        self._db = StorageManagerDB(get_default_db_path())
        self._db.initialize()

        # Histórico de mensagens do chat (formato Ollama)
        self._messages: list[dict] = []
        self._current_response_text = ""
        self._worker: OllamaAgentWorker | OllamaChatWorker | None = None

        self._build_ui()
        self._refresh_models()

    # ─────────────────────────────────────────────────────────────────────────
    # Construção da UI
    # ─────────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # ── Cabeçalho ──────────────────────────────────────────────────────
        header = QHBoxLayout()
        title = QLabel("Assistente IA Local (Ollama)")
        title.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; font-size: 18px; font-weight: 600;"
        )
        header.addWidget(title)
        header.addStretch()

        header.addWidget(QLabel("Modelo:"))
        self.combo_models = QComboBox()
        self.combo_models.setFixedWidth(200)
        self.combo_models.setFixedHeight(30)
        header.addWidget(self.combo_models)

        btn_refresh = QPushButton("🔄 Atualizar")
        btn_refresh.setFixedWidth(90)
        btn_refresh.setFixedHeight(30)
        btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_refresh.setProperty("cssClass", "secondary")
        btn_refresh.clicked.connect(self._refresh_models)
        header.addWidget(btn_refresh)

        layout.addLayout(header)

        # ── Linha separadora ────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background-color: {Colors.BORDER_SUBTLE}; max-height: 1px;")
        layout.addWidget(sep)

        # ── Área de Chat ────────────────────────────────────────────────────
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setStyleSheet(f"""
            QTextEdit {{
                background-color: {Colors.BG_SECONDARY};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: 8px;
                padding: 10px;
                font-size: 14px;
            }}
        """)
        layout.addWidget(self.chat_display, stretch=1)

        # ── Input ───────────────────────────────────────────────────────────
        input_layout = QHBoxLayout()
        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText(
            "Pergunte algo sobre armazenamento ou peça ao assistente para agir…"
        )
        self.input_box.setFixedHeight(45)
        self.input_box.returnPressed.connect(self._send_message)
        self.input_box.setStyleSheet(f"""
            QLineEdit {{
                background-color: {Colors.BG_INPUT};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: 8px;
                padding: 0 15px;
                font-size: 14px;
            }}
            QLineEdit:focus {{
                border-color: {Colors.ACCENT_CYAN};
            }}
        """)
        input_layout.addWidget(self.input_box, stretch=1)

        self.btn_send = QPushButton("Enviar")
        self.btn_send.setFixedHeight(45)
        self.btn_send.setFixedWidth(100)
        self.btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_send.clicked.connect(self._send_message)
        input_layout.addWidget(self.btn_send)

        layout.addLayout(input_layout)

    # ─────────────────────────────────────────────────────────────────────────
    # Modelos Ollama
    # ─────────────────────────────────────────────────────────────────────────

    def _refresh_models(self):
        """Busca modelos disponíveis no Ollama e atualiza o combo_models."""
        self.combo_models.clear()

        if not self._client.is_available():
            self.combo_models.addItem("Ollama não detectado")
            self.combo_models.setEnabled(False)
            self.input_box.setEnabled(False)
            self.btn_send.setEnabled(False)
            self.chat_display.setHtml(
                f"<div style='color:{Colors.STATUS_RED};'>"
                "<b>Ollama não está rodando!</b><br><br>"
                "Instale o Ollama (<i>https://ollama.com</i>) e deixe-o rodando em "
                "<code>localhost:11434</code> para usar o Assistente Local."
                "</div>"
            )
            return

        models = self._client.get_models()
        if not models:
            self.combo_models.addItem("Nenhum modelo baixado")
            self.combo_models.setEnabled(False)
            self.input_box.setEnabled(False)
            self.btn_send.setEnabled(False)
            self.chat_display.setHtml(
                f"<div style='color:{Colors.STATUS_YELLOW};'>"
                "<b>Nenhum modelo baixado!</b><br><br>"
                "Abra um terminal e rode: <code>ollama run qwen2.5</code> "
                "ou outro modelo de sua preferência."
                "</div>"
            )
            return

        self.combo_models.setEnabled(True)
        self.input_box.setEnabled(True)
        self.btn_send.setEnabled(True)
        self.combo_models.addItems(models)
        self.chat_display.setHtml(
            f"<div style='color:{Colors.TEXT_SECONDARY}; text-align:center;'>"
            "<i>✅ Ollama conectado. Modo Agente com Tool-Calling ativo.<br>"
            "Como posso ajudar a otimizar seu PC hoje?</i><br>"
            "</div>"
        )
        self._messages.clear()

    # ─────────────────────────────────────────────────────────────────────────
    # Contexto dinâmico do sistema
    # ─────────────────────────────────────────────────────────────────────────

    def _get_system_context(self) -> str:
        """
        Gera mensagem de sistema com estado atual do PC injetado dinamicamente.

        Inclui: partições, sugestões pendentes, resumo de duplicatas e histórico.
        """
        lines = [
            "Você é o GestaoPC Assistente, especializado em gestão de armazenamento Windows.",
            "Você tem acesso a tools para consultar e gerenciar o sistema de arquivos.",
            "",
            "REGRA CRÍTICA DE SEGURANÇA: Antes de qualquer ação executiva "
            "(move_to_trash, move_file, apply_suggestion, undo_last_operation, set_disk_role), "
            "SEMPRE chame request_confirmation() primeiro para obter o token de autorização.",
            "",
            "=== ESTADO ATUAL DO SISTEMA ===",
        ]

        # ── Partições ──────────────────────────────────────────────────────
        try:
            parts = tb.list_partitions()
            lines.append("\n[Partições]")
            for p in parts:
                if "error" not in p:
                    lines.append(
                        f"  {p.get('letter', '?')} — {p.get('media_type', '?')} "
                        f"({p.get('fstype', '?')}) — "
                        f"Total: {p.get('total_gb', 0):.1f} GB, "
                        f"Livre: {p.get('free_gb', 0):.1f} GB "
                        f"({p.get('used_pct', 0):.1f}% usado)"
                    )
        except Exception:
            lines.append("[Partições] — Não disponível")

        # ── Sugestões pendentes ─────────────────────────────────────────────
        try:
            suggestions = tb.list_suggestions(limit=5)
            if suggestions and "error" not in suggestions[0]:
                lines.append(
                    f"\n[Sugestões Pendentes — {len(suggestions)} item(ns)]"
                )
                for s in suggestions:
                    fname = Path(s.get("file_path", "?")).name
                    lines.append(
                        f"  #{s['id']} {s.get('rule_name', '?')}: "
                        f"{fname} → {s.get('action', '?')}"
                    )
            else:
                lines.append(
                    "\n[Sugestões] — Nenhuma (execute varredura via interface primeiro)"
                )
        except Exception:
            lines.append("\n[Sugestões] — Não disponível")

        # ── Duplicatas (resumo) ─────────────────────────────────────────────
        try:
            dups = tb.find_duplicates(limit=3, min_size_mb=100.0)
            if dups and "error" not in dups[0]:
                wasted = sum(d.get("wasted_bytes", 0) for d in dups)
                lines.append(
                    f"\n[Duplicatas — {len(dups)} grupo(s) ≥100 MB detectados, "
                    f"~{_human_size(wasted)} desperdiçados]"
                )
            else:
                lines.append(
                    "\n[Duplicatas] — Nenhuma detectada no índice (execute varredura primeiro)"
                )
        except Exception:
            lines.append("\n[Duplicatas] — Não disponível")

        # ── Histórico recente ───────────────────────────────────────────────
        try:
            history = tb.get_history(limit=5)
            if history and "error" not in history[0]:
                lines.append(f"\n[Últimas {len(history)} Operações]")
                for h in history:
                    status = "✓" if h.get("success") else "✗"
                    fname = Path(h.get("source_path", "?")).name
                    src = h.get("source", "ui")
                    lines.append(
                        f"  {status} {h.get('operation', '?')} — {fname} (por {src})"
                    )
            else:
                lines.append("\n[Histórico] — Nenhuma operação registrada")
        except Exception:
            lines.append("\n[Histórico] — Não disponível")

        lines += [
            "",
            "=== FIM DO CONTEXTO ===",
            "",
            "Responda de forma clara e concisa. Para dados detalhados, use as tools disponíveis.",
        ]
        return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────────────────
    # Envio de mensagem
    # ─────────────────────────────────────────────────────────────────────────

    def _send_message(self):
        text = self.input_box.text().strip()
        if not text:
            return

        model = self.combo_models.currentText()
        if not model or model.startswith("Ollama") or model.startswith("Nenhum"):
            return

        # Exibir mensagem do usuário
        self.chat_display.append(
            f"<br><b style='color:{Colors.ACCENT_CYAN};'>Você:</b><br>{text}<br>"
        )
        self.input_box.clear()
        self.input_box.setEnabled(False)
        self.btn_send.setEnabled(False)

        # Inicializar contexto de sistema na primeira mensagem
        if not self._messages:
            self._messages.append({
                "role": "system",
                "content": self._get_system_context(),
            })

        self._messages.append({"role": "user", "content": text})

        # Cabeçalho da resposta
        self.chat_display.append(
            f"<b style='color:{Colors.STATUS_GREEN};'>Assistente ({model}):</b>"
        )

        # Iniciar worker de agente com tools
        self._current_response_text = ""
        tools = tb.get_tool_schemas()

        self._worker = OllamaAgentWorker(model, self._messages, tools, self)
        self._worker.tool_call_started.connect(self._on_tool_call_started)
        self._worker.tool_call_finished.connect(self._on_tool_call_finished)
        self._worker.text_received.connect(self._on_agent_text)
        self._worker.error_occurred.connect(self._on_agent_error)
        self._worker.finished_response.connect(self._on_response_finished)
        self._worker.start()

    # ─────────────────────────────────────────────────────────────────────────
    # Handlers dos sinais do worker
    # ─────────────────────────────────────────────────────────────────────────

    def _on_tool_call_started(self, tool_name: str, args_summary: str):
        """Exibe indicador visual quando o modelo inicia uma chamada de tool."""
        indicator = f"🔧 <i style='color:{Colors.STATUS_YELLOW};'>Chamando: <b>{tool_name}</b>"
        if args_summary:
            indicator += f"({args_summary})"
        indicator += "…</i>"
        self.chat_display.append(indicator)
        self._scroll_to_bottom()

    def _on_tool_call_finished(self, tool_name: str, result_summary: str):
        """Exibe indicador visual após tool retornar resultado."""
        # Detectar se é erro ou sucesso pelo conteúdo do resultado
        is_error = '"error"' in result_summary
        icon = "⚠️" if is_error else "✅"
        color = Colors.STATUS_RED if is_error else Colors.TEXT_SECONDARY
        # Truncar resultado para UI
        display = result_summary[:150] + ("…" if len(result_summary) > 150 else "")
        self.chat_display.append(
            f"{icon} <i style='color:{color};'><b>{tool_name}</b>: {display}</i>"
        )
        self._scroll_to_bottom()

    def _on_agent_text(self, content: str):
        """Exibe o texto final do modelo."""
        self._current_response_text = content
        # Substituir quebras de linha por <br> para HTML
        html_content = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        html_content = html_content.replace("\n", "<br>")
        self.chat_display.append(html_content)
        self._scroll_to_bottom()

    def _on_agent_error(self, message: str):
        """Exibe mensagem de erro no chat."""
        self.chat_display.append(
            f"<span style='color:{Colors.STATUS_RED};'>❌ {message}</span>"
        )
        self._scroll_to_bottom()

    def _on_response_finished(self):
        """Encerra o turno: salva resposta no histórico e reativa input."""
        if self._current_response_text:
            self._messages.append({
                "role": "assistant",
                "content": self._current_response_text,
            })
        self.chat_display.append("<br>")

        self.input_box.setEnabled(True)
        self.btn_send.setEnabled(True)
        self.input_box.setFocus()

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers de chat simples (streaming, sem tools) — mantido para fallback
    # ─────────────────────────────────────────────────────────────────────────

    def _on_token(self, token: str):
        """Recebe token de streaming do OllamaChatWorker (fallback)."""
        self._current_response_text += token
        cursor = self.chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.chat_display.setTextCursor(cursor)
        self.chat_display.insertPlainText(token)
        self._scroll_to_bottom()

    # ─────────────────────────────────────────────────────────────────────────
    # Utilitários de UI
    # ─────────────────────────────────────────────────────────────────────────

    def _scroll_to_bottom(self):
        """Scrolla o chat_display para o final."""
        scrollbar = self.chat_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
