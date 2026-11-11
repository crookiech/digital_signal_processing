import threading
from scapy.all import *
from scapy.layers.dhcp import BOOTP, DHCP

class MiniDhcpServer(threading.Thread):
    def __init__(self, interface, pool_start, pool_end, subnet_mask, gateway):
        super().__init__()
        self.interface = interface
        self.pool_start = pool_start
        self.pool_end = pool_end
        self.subnet_mask = subnet_mask
        self.gateway = gateway
        self.running = True
        self.leases = {}  # Словарь {mac: ip}
        self._stop_event = threading.Event()

    def run(self):
        # Слушаем DHCP пакеты на указанном интерфейсе
        # timeout=1 заставляет sniff просыпаться раз в секунду и проверять stop_filter
        sniff(filter="udp and (port 67 or 68)", prn=self.handle_packet, 
              iface=self.interface, store=0, 
              stop_filter=lambda x: self._stop_event.is_set(),
              timeout=1) 
        
    def handle_packet(self, packet):
        if not packet.haslayer(DHCP):
            return

        client_mac = packet[Ether].src
        dhcp_options = packet[DHCP].options
        msg_type = None
        for opt in dhcp_options:
            if isinstance(opt, tuple) and opt[0] == 'message-type':
                msg_type = opt[1]
                break
        
        # Теперь печатаем, когда msg_type уже определён
        print(f"ПОЛУЧЕН ПАКЕТ от {client_mac}, тип: {msg_type}")

        client_mac = packet[Ether].src
        dhcp_options = packet[DHCP].options
        msg_type = None
        for opt in dhcp_options:
            if isinstance(opt, tuple) and opt[0] == 'message-type':
                msg_type = opt[1]
                break

        # 1. DHCP DISCOVER (Поиск сервера)
        if msg_type == 1:
            assigned_ip = None
            # Простой поиск свободного IP
            start = int(self.pool_start.split('.')[-1])
            end = int(self.pool_end.split('.')[-1])
            prefix = '.'.join(self.pool_start.split('.')[:-1])
            
            for i in range(start, end + 1):
                ip = f"{prefix}.{i}"
                if ip not in self.leases.values():
                    assigned_ip = ip
                    break
            
            if not assigned_ip:
                return

            # Отправляем OFFER
            offer = (
                Ether(src=get_if_hwaddr(self.interface), dst=client_mac) /
                IP(src=self.gateway, dst="255.255.255.255") /
                UDP(sport=67, dport=68) /
                BOOTP(op=2, yiaddr=assigned_ip, siaddr=self.gateway, 
                      chaddr=bytes.fromhex(client_mac.replace(':', ''))) /
                DHCP(options=[("message-type", "offer"), ("server_id", self.gateway), 
                              ("subnet_mask", self.subnet_mask), ("router", self.gateway), "end"])
            )
            sendp(offer, iface=self.interface, verbose=0)

        # 2. DHCP REQUEST (Подтверждение)
        elif msg_type == 3:
            requested_ip = None
            for opt in dhcp_options:
                if isinstance(opt, tuple) and opt[0] == 'requested_addr':
                    requested_ip = opt[1]
                    break
            
            if requested_ip:
                self.leases[client_mac] = requested_ip
                # Отправляем ACK
                ack = (
                    Ether(src=get_if_hwaddr(self.interface), dst=client_mac) /
                    IP(src=self.gateway, dst="255.255.255.0") /
                    UDP(sport=67, dport=68) /
                    BOOTP(op=2, yiaddr=requested_ip, siaddr=self.gateway, 
                          chaddr=bytes.fromhex(client_mac.replace(':', ''))) /
                    DHCP(options=[("message-type", "ack"), ("server_id", self.gateway), 
                                  ("subnet_mask", self.subnet_mask), ("router", self.gateway), "end"])
                )
                sendp(ack, iface=self.interface, verbose=0)

    def get_leases(self):
        # Возвращает словарь {mac: ip}
        return self.leases
    
    def stop(self):
        self._stop_event.set()
        # Ждем завершения потока, но не вечно (максимум 3 секунды)
        self.join(timeout=3)