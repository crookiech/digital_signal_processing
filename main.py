import ctypes
import sys
import os
from PyQt6.QtWidgets import QApplication
from main_window import MultimeterApp

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

if not is_admin():
    print("Запрос прав администратора...")
    # Получаем путь к текущему скрипту (main.py)
    script = os.path.abspath(__file__)
    
    # Формируем команду для запуска python.exe с нашим скриптом
    # sys.executable — это путь к python.exe (даже под отладчиком это работает)
    params = f'"{script}"'
    
    # Запускаем новый процесс от имени администратора
    # lpVerb="runas" вызывает UAC
    # nShow=1 означает показать окно
    ret = ctypes.windll.shell32.ShellExecuteW(
        None, 
        "runas", 
        sys.executable, 
        params, 
        None, 
        1
    )
    
    # Если ret <= 32, значит запуск не удался (например, отказ в UAC)
    if ret <= 32:
        print("Не удалось получить права администратора. Запустите вручную от имени администратора.")
    
    # Завершаем текущий процесс (отладчик)
    sys.exit(0)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MultimeterApp()
    window.show()
    sys.exit(app.exec())