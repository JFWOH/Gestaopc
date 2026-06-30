"""Captura screenshot da janela Gerenciador de PC."""
import ctypes
import time
import ctypes.wintypes

user32 = ctypes.windll.user32

# Encontrar a janela
hwnd = user32.FindWindowW(None, "Gerenciador de PC  \u2014  Storage Manager")
if not hwnd:
    print("Janela nao encontrada!")
    exit(1)

print(f"Handle: {hwnd}")

# Trazer para frente
user32.ShowWindow(hwnd, 5)  # SW_SHOW
user32.SetForegroundWindow(hwnd)
time.sleep(0.5)

# Capturar screenshot
from PIL import ImageGrab  # noqa: E402  (import lazy: só ao capturar)
time.sleep(0.3)
img = ImageGrab.grab()
img.save("screenshot_gui.png")
print("Screenshot salvo com sucesso!")
