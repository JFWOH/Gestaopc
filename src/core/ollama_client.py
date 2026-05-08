import json
import logging
import urllib.request
import urllib.error
from typing import Iterator

logger = logging.getLogger(__name__)

class OllamaClient:
    """Cliente simples para interagir com a API local do Ollama."""
    
    def __init__(self, host: str = "http://localhost:11434"):
        self.host = host

    def is_available(self) -> bool:
        """Verifica se o servidor Ollama está rodando e acessível."""
        try:
            req = urllib.request.Request(self.host)
            with urllib.request.urlopen(req, timeout=2) as response:
                return response.status == 200
        except Exception:
            return False

    def get_models(self) -> list[str]:
        """Retorna uma lista com os nomes dos modelos instalados."""
        try:
            req = urllib.request.Request(f"{self.host}/api/tags")
            with urllib.request.urlopen(req, timeout=3) as response:
                data = json.loads(response.read().decode("utf-8"))
                return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.warning(f"Erro ao buscar modelos Ollama: {e}")
            return []

    def chat_stream(self, model: str, messages: list[dict]) -> Iterator[str]:
        """Envia mensagens e retorna um iterador (stream) com a resposta do modelo."""
        url = f"{self.host}/api/chat"
        payload = json.dumps({"model": model, "messages": messages}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        
        try:
            with urllib.request.urlopen(req) as response:
                for line in response:
                    if line:
                        try:
                            data = json.loads(line.decode("utf-8"))
                            yield data.get("message", {}).get("content", "")
                            if data.get("done"):
                                break
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            logger.error(f"Erro no chat Ollama: {e}")
            yield f"\n[Erro de conexão com o modelo '{model}': {str(e)}]"
