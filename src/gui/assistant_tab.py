import logging
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit, 
    QPushButton, QComboBox, QLabel, QMessageBox, QFrame
)
from PyQt6.QtGui import QTextCursor

from src.core.ollama_client import OllamaClient
from src.core.storage_db import StorageManagerDB, get_default_db_path
from src.core.scanner import StorageScanner
from src.gui.styles import Colors

logger = logging.getLogger(__name__)

class OllamaChatWorker(QThread):
    """Thread que realiza a comunicação com o Ollama sem travar a UI."""
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


class AssistantTab(QWidget):
    """
    Aba do Assistente IA local, conectando o aplicativo ao Ollama.
    Gera contexto do sistema automaticamente e envia para a IA.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = OllamaClient()
        self._db = StorageManagerDB(get_default_db_path())
        self._db.initialize()
        
        # Histórico de mensagens do chat (formato Ollama)
        self._messages: list[dict] = []
        
        self._build_ui()
        self._refresh_models()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        # Cabeçalho
        header = QHBoxLayout()
        title = QLabel("Assistente IA Local (Ollama)")
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-size: 18px; font-weight: 600;")
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

        # Linha separadora
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background-color: {Colors.BORDER_SUBTLE}; max-height: 1px;")
        layout.addWidget(sep)

        # Área de Chat
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

        # Input do usuário
        input_layout = QHBoxLayout()
        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("Pergunte algo sobre seu armazenamento ou otimização do PC...")
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

    def _refresh_models(self):
        """Busca os modelos disponíveis no Ollama e atualiza a combo_models."""
        self.combo_models.clear()
        if not self._client.is_available():
            self.combo_models.addItem("Ollama não detectado")
            self.combo_models.setEnabled(False)
            self.input_box.setEnabled(False)
            self.btn_send.setEnabled(False)
            self.chat_display.setHtml(
                f"<div style='color:{Colors.STATUS_RED};'>"
                "<b>Ollama não está rodando!</b><br><br>"
                "Por favor, instale o Ollama (https://ollama.com) e deixe-o rodando em <i>localhost:11434</i> "
                "para utilizar o Assistente Local."
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
                "<b>Nenhum modelo baixado no Ollama!</b><br><br>"
                "Abra um terminal e rode: <code>ollama run llama3</code> ou outro modelo de sua preferência."
                "</div>"
            )
            return

        self.combo_models.setEnabled(True)
        self.input_box.setEnabled(True)
        self.btn_send.setEnabled(True)
        self.combo_models.addItems(models)
        self.chat_display.setHtml(
            f"<div style='color:{Colors.TEXT_SECONDARY}; text-align:center;'>"
            "<i>Sistemas Prontos. Ollama Conectado. Como posso ajudar a otimizar o seu PC hoje?</i><br><br>"
            "</div>"
        )
        self._messages.clear()

    def _get_system_context(self) -> str:
        """Gera o contexto dinâmico do PC injetando status dos discos."""
        scanner = StorageScanner()
        parts = scanner.list_partitions()
        
        context_lines = [
            "Você é o GestaoPC Assistente, uma IA super inteligente especializada em gestão de arquivos e hardware Windows.",
            "O usuário possui o seguinte contexto de armazenamento em sua máquina agora mesmo:"
        ]
        for p in parts:
            context_lines.append(
                f"- Disco [{p.letter}]: Sistema de Arquivos {p.fstype}, "
                f"Capacidade {p.total_gb:.1f}GB, Livre {p.free_gb:.1f}GB, "
                f"Em uso: {(p.used_bytes / max(p.total_bytes, 1) * 100):.1f}%."
            )
        
        context_lines.append("\nResponda as dúvidas do usuário de forma concisa, educada e oferecendo dicas reais de otimização para este ambiente.")
        
        return "\n".join(context_lines)

    def _send_message(self):
        text = self.input_box.text().strip()
        if not text:
            return

        model = self.combo_models.currentText()
        if not model or model.startswith("Ollama"):
            return

        # Anexar à UI (Sua mensagem)
        self.chat_display.append(
            f"<br><b style='color:{Colors.ACCENT_CYAN};'>Você:</b><br>{text}<br>"
        )
        self.input_box.clear()
        self.input_box.setEnabled(False)
        self.btn_send.setEnabled(False)

        # Preparar mensagens para a API
        if not self._messages:
            self._messages.append({
                "role": "system",
                "content": self._get_system_context()
            })
        
        self._messages.append({"role": "user", "content": text})
        
        # Preparar a interface para a resposta
        self.chat_display.append(f"<b style='color:{Colors.STATUS_GREEN};'>Assistente ({model}):</b>")
        
        # Iniciar Worker
        self._current_response_text = ""
        self._worker = OllamaChatWorker(model, self._messages, self)
        self._worker.token_received.connect(self._on_token)
        self._worker.finished_response.connect(self._on_response_finished)
        self._worker.start()

    def _on_token(self, token: str):
        """Conforme os tokens chegam do LLM, anexa visualmente à UI."""
        self._current_response_text += token
        # Substitui quebras de linha reais por <br> no visual
        # Não é perfeito para Markdown avançado, mas serve ao propósito interativo.
        cursor = self.chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.chat_display.setTextCursor(cursor)
        
        # Para evitar reinserir a linha toda, usamos o método insertText do cursor
        self.chat_display.insertPlainText(token)
        
        # Scrolla para o fim automaticamente
        scrollbar = self.chat_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_response_finished(self):
        """Conclusão do turno da IA."""
        self._messages.append({"role": "assistant", "content": self._current_response_text})
        self.chat_display.append("<br>") # Quebra final extra
        
        self.input_box.setEnabled(True)
        self.btn_send.setEnabled(True)
        self.input_box.setFocus()
