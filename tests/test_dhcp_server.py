import unittest
from unittest.mock import patch

from scapy.all import BOOTP, DHCP, Ether, IP, UDP
from dhcp_server import MiniDhcpServer


def request(kind, mac="aa:bb:cc:dd:ee:01", ciaddr="0.0.0.0", flags=0x8000, **options):
    return (
        Ether(src=mac, dst="ff:ff:ff:ff:ff:ff")
        / IP(src="0.0.0.0", dst="255.255.255.255")
        / UDP(sport=68, dport=67)
        / BOOTP(op=1, xid=12345678, flags=flags, ciaddr=ciaddr,
                chaddr=bytes.fromhex(mac.replace(":", "")))
        / DHCP(options=[("message-type", kind), *options.items(), "end"])
    )


class DhcpTests(unittest.TestCase):
    def setUp(self):
        self.server = MiniDhcpServer(
            "Ethernet", "192.168.137.150", "192.168.137.200",
            "255.255.255.0", "", "192.168.137.151")
        self.server._server_mac = "00:11:22:33:44:55"
        self.sender = patch("dhcp_server.sendp").start()
        self.addCleanup(patch.stopall)

    def test_offer_and_ack_preserve_transaction_and_use_pc_address(self):
        discovery = request(1)
        self.server.handle_packet(discovery)
        reply = self.sender.call_args.args[0]
        # Serialize/parse using real Scapy, without any network I/O.
        reply = Ether(bytes(reply))
        self.assertEqual(reply[BOOTP].xid, discovery[BOOTP].xid)
        self.assertEqual(reply[BOOTP].chaddr, discovery[BOOTP].chaddr.ljust(16, b"\0"))
        self.assertEqual(reply[BOOTP].yiaddr, "192.168.137.150")
        self.assertEqual(reply[IP].src, "192.168.137.151")
        self.assertEqual(reply[IP].dst, "255.255.255.255")
        self.assertEqual(dict(reply[DHCP].options[:-1])["server_id"], "192.168.137.151")
        self.assertEqual(self.server.get_leases(), {})
        self.server.handle_packet(request(
            3, requested_addr="192.168.137.150", server_id="192.168.137.151"))
        self.assertEqual(self.server.get_leases(), {"aa:bb:cc:dd:ee:01": "192.168.137.150"})

    def test_second_client_cannot_receive_reserved_or_server_ip(self):
        self.server.handle_packet(request(1))
        self.server.handle_packet(request(1, mac="aa:bb:cc:dd:ee:02"))
        self.assertEqual(self.sender.call_args.args[0][BOOTP].yiaddr, "192.168.137.152")

    def test_previous_address_outside_pool_gets_nak(self):
        self.server.handle_packet(request(3, requested_addr="192.168.137.100"))
        reply = Ether(bytes(self.sender.call_args.args[0]))
        self.assertEqual(reply[BOOTP].yiaddr, "0.0.0.0")
        self.assertEqual(reply[IP].dst, "255.255.255.255")
        self.assertEqual(dict(reply[DHCP].options[:-1])["message-type"], 6)
        self.assertEqual(self.server.get_leases(), {})

    def test_request_for_another_server_is_ignored(self):
        self.server.handle_packet(request(
            3, requested_addr="192.168.137.150", server_id="192.168.137.99"))
        self.sender.assert_not_called()

    def test_renewal_without_requested_address_uses_ciaddr(self):
        self.server.handle_packet(request(3, ciaddr="192.168.137.150", flags=0))
        reply = self.sender.call_args.args[0]
        self.assertEqual(reply[IP].dst, "192.168.137.150")
        self.assertEqual(self.server.get_leases(), {"aa:bb:cc:dd:ee:01": "192.168.137.150"})

    def test_capture_continues_after_idle_timeout_and_stops(self):
        count = 0

        def capture(**kwargs):
            nonlocal count
            count += 1
            kwargs["started_callback"]()
            if count == 3:
                self.server._stop_event.set()

        with patch("dhcp_server.sniff", side_effect=capture), \
                patch("dhcp_server.get_if_hwaddr", return_value=self.server._server_mac):
            self.server.run()
        self.assertEqual(count, 3)
        self.assertFalse(self.server.running)

    def test_capture_error_is_exposed_to_gui(self):
        with patch("dhcp_server.sniff", side_effect=RuntimeError("Npcap unavailable")), \
                patch("dhcp_server.get_if_hwaddr", return_value=self.server._server_mac):
            self.server.run()
        self.assertIn("Npcap unavailable", self.server.error)
        self.assertFalse(self.server.running)


if __name__ == "__main__":
    unittest.main()
