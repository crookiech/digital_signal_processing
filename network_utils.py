import socket

def get_pc_network_info():
    ip = "Не определен"
    mask = "Не определен"
    gateway = "Не определен"
    
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        
        import subprocess
        import re
        
        result = subprocess.run(['ipconfig'], capture_output=True, text=True, encoding='cp866')
        output = result.stdout
        
        blocks = output.split('\n\n')
        for block in blocks:
            if ip in block:
                mask_match = re.search(r'Маска подсети.*?:\s*([\d\.]+)', block)
                if mask_match:
                    mask = mask_match.group(1)
                
                gw_match = re.search(r'Основной шлюз.*?:\s*([\d\.]+)', block)
                if gw_match:
                    gateway = gw_match.group(1)
                break
                
    except Exception as e:
        print(f"Ошибка получения сетевых настроек: {e}")
        
    return ip, mask, gateway