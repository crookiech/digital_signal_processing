import threading
import time
from ipaddress import IPv4Address, IPv4Network

from scapy.all import Ether, IP, UDP, get_if_hwaddr, sendp, sniff
from scapy.layers.dhcp import BOOTP, DHCP


class MiniDhcpServer(threading.Thread):
    def __init__(self, interface, pool_start, pool_end, subnet_mask, gateway, server_ip):
        super().__init__(daemon=True)
        self.interface = interface
        self.pool_start = pool_start
        self.pool_end = pool_end
        self.subnet_mask = subnet_mask
        self.gateway = gateway
        self.server_ip = str(IPv4Address(server_ip))
        self.network = IPv4Network(f"{server_ip}/{subnet_mask}", strict=False)
        self._pool_start = int(IPv4Address(pool_start))
        self._pool_end = int(IPv4Address(pool_end))
        if (self._pool_start > self._pool_end
                or IPv4Address(pool_start) not in self.network
                or IPv4Address(pool_end) not in self.network):
            raise ValueError("Пул DHCP должен находиться в подсети выбранного адаптера.")
        if gateway:
            IPv4Address(gateway)
        self.running = False
        self.error = None
        self.leases = {}
        self._offers = {}
        self._offer_expiry = {}
        self._lease_expiry = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._server_mac = None

    def _on_ready(self):
        self.running = True

    def run(self):
        try:
            self._server_mac = get_if_hwaddr(self.interface)
            # timeout завершает один sniff; цикл продолжает слушать до stop().
            while not self._stop_event.is_set():
                sniff(
                    filter="udp and (port 67 or 68)",
                    prn=self.handle_packet,
                    iface=self.interface,
                    store=False,
                    stop_filter=lambda packet: self._stop_event.is_set(),
                    timeout=1,
                    started_callback=self._on_ready,
                )
                # Scapy может перехватить исключение из обработчика пакета.
                if self.error:
                    break
        except Exception as exc:
            self.error = str(exc)
        finally:
            self.running = False

    def _available(self, address, client_mac):
        try:
            ip = IPv4Address(address)
        except ValueError:
            return False
        if not self._pool_start <= int(ip) <= self._pool_end:
            return False
        if str(ip) in {self.server_ip, self.gateway}:
            return False
        if ip in {self.network.network_address, self.network.broadcast_address}:
            return False
        with self._lock:
            used = {value for mac, value in self.leases.items() if mac != client_mac}
        used.update(value for mac, value in self._offers.items() if mac != client_mac)
        return str(ip) not in used

    def _reply(self, packet, address, message_type):
        request = packet[BOOTP]
        # Сохраняем идентификатор транзакции и аппаратный адрес клиента.
        if message_type == "nak":
            destination_ip = "255.255.255.255"
            destination_mac = "ff:ff:ff:ff:ff:ff"
        elif request.ciaddr != "0.0.0.0":
            destination_ip = request.ciaddr
            destination_mac = packet[Ether].src
        elif int(request.flags) & 0x8000:
            destination_ip = "255.255.255.255"
            destination_mac = "ff:ff:ff:ff:ff:ff"
        else:
            destination_ip = address
            destination_mac = packet[Ether].src
        options = [
            ("message-type", message_type),
            ("server_id", self.server_ip),
        ]
        if message_type != "nak":
            options.extend([("subnet_mask", self.subnet_mask), ("lease_time", 3600)])
            if self.gateway:
                options.append(("router", self.gateway))
        options.append("end")
        response = (
            Ether(src=self._server_mac, dst=destination_mac)
            / IP(src=self.server_ip, dst=destination_ip)
            / UDP(sport=67, dport=68)
            / BOOTP(
                op=2, htype=request.htype, hlen=request.hlen,
                xid=request.xid, flags=request.flags,
                ciaddr=request.ciaddr if message_type != "nak" else "0.0.0.0",
                yiaddr=address,
                siaddr=self.server_ip, chaddr=request.chaddr,
            )
            / DHCP(options=options)
        )
        sendp(response, iface=self.interface, verbose=False)

    def handle_packet(self, packet):
        if self._stop_event.is_set():
            return
        if not all(packet.haslayer(layer) for layer in (Ether, BOOTP, DHCP)):
            return
        request = packet[BOOTP]
        if request.op != 1 or request.giaddr != "0.0.0.0":
            return
        options = {
            opt[0]: opt[1] for opt in packet[DHCP].options
            if isinstance(opt, tuple) and len(opt) > 1
        }
        message_type = options.get("message-type")
        client_mac = packet[Ether].src
        # Reservations must not exhaust the pool after abandoned DISCOVERs.
        now = time.monotonic()
        for mac, expiry in list(self._offer_expiry.items()):
            if expiry <= now:
                self._offers.pop(mac, None)
                self._offer_expiry.pop(mac, None)
        with self._lock:
            for mac, expiry in list(self._lease_expiry.items()):
                if expiry <= now:
                    self.leases.pop(mac, None)
                    self._lease_expiry.pop(mac, None)
        selected_server = options.get("server_id")
        if selected_server and selected_server != self.server_ip:
            self._offers.pop(client_mac, None)
            self._offer_expiry.pop(client_mac, None)
            return
        try:
            if message_type == 1:  # DISCOVER
                with self._lock:
                    address = self.leases.get(client_mac)
                address = address or self._offers.get(client_mac)
                if not address or not self._available(address, client_mac):
                    address = next(
                        (str(IPv4Address(ip))
                         for ip in range(self._pool_start, self._pool_end + 1)
                         if self._available(str(IPv4Address(ip)), client_mac)),
                        None,
                    )
                if address:
                    self._offers[client_mac] = address
                    self._offer_expiry[client_mac] = now + 60
                    self._reply(packet, address, "offer")
                    print(f"DHCP OFFER: {client_mac} -> {address}")
            elif message_type == 3:  # REQUEST, включая продление аренды
                address = options.get("requested_addr")
                if not address and request.ciaddr != "0.0.0.0":
                    address = request.ciaddr
                if address and self._available(address, client_mac):
                    self._reply(packet, address, "ack")
                    with self._lock:
                        self.leases.pop(client_mac, None)
                        self.leases[client_mac] = address
                        self._lease_expiry[client_mac] = now + 3600
                    self._offers.pop(client_mac, None)
                    self._offer_expiry.pop(client_mac, None)
                    print(f"DHCP ACK: {client_mac} -> {address}")
                elif address:
                    # A device may request its previous address after Apply.
                    # Ask it to restart discovery instead of silently waiting.
                    self._reply(packet, "0.0.0.0", "nak")
            elif message_type == 7:  # RELEASE
                with self._lock:
                    self.leases.pop(client_mac, None)
                    self._lease_expiry.pop(client_mac, None)
                self._offers.pop(client_mac, None)
                self._offer_expiry.pop(client_mac, None)
        except Exception as exc:
            self.error = f"Ошибка обработки DHCP: {exc}"
            self._stop_event.set()

    def get_leases(self):
        with self._lock:
            return dict(self.leases)

    def stop(self):
        self._stop_event.set()
        if self.is_alive():
            self.join(timeout=3)
