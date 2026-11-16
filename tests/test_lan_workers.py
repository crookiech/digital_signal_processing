import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from lan_workers import open_instrument, prepare_lan


class InstrumentTests(unittest.TestCase):
    def test_usbtmc_uses_message_boundary_and_lan_keeps_newline(self):
        for resource_name, expected in (
                ("USB0::0x0001::0x0002::123::INSTR", None),
                ("TCPIP0::192.168.137.150::INSTR", "\n")):
            with self.subTest(resource=resource_name):
                instrument = Mock()
                instrument.query.return_value = "UNI-T,UT8805,123,1.0"
                manager = Mock()
                manager.open_resource.return_value = instrument
                open_instrument(manager, resource_name)
                self.assertEqual(instrument.read_termination, expected)
                self.assertEqual(instrument.write_termination, "\n")

    def test_actual_firmware_identity_without_e_suffix_is_accepted(self):
        instrument = Mock()
        instrument.query.return_value = "UNI-T,UT8805,AMM2522500052,SW V1.81.001"
        manager = Mock()
        manager.open_resource.return_value = instrument
        result, _ = open_instrument(manager, "TCPIP0::192.168.137.150::INSTR", True)
        self.assertIs(result, instrument)
        instrument.write.assert_any_call("CONF:VOLT:DC")
        instrument.close.assert_not_called()

    def test_model_name_in_another_identity_field_does_not_bypass_check(self):
        for identity in ("Other,Generator,UT8805E,1.0", "UNI-T,UT8805EX,123,1.0"):
            with self.subTest(identity=identity):
                instrument = Mock()
                instrument.query.return_value = identity
                manager = Mock()
                manager.open_resource.return_value = instrument
                with self.assertRaises(ValueError):
                    open_instrument(manager, "TCPIP0::192.168.137.150::INSTR", True)
                instrument.write.assert_not_called()
                instrument.close.assert_called_once()

    def test_identity_precedes_measurement_commands(self):
        instrument = Mock()
        instrument.query.return_value = "UNI-T,UT8805E,123,1.0\n"
        manager = Mock()
        manager.open_resource.return_value = instrument
        result, identity = open_instrument(manager, "TCPIP0::192.168.137.150::INSTR", True)
        self.assertIs(result, instrument)
        self.assertIn("UT8805E", identity)
        calls = instrument.method_calls
        self.assertEqual(calls[0][0], "query")
        self.assertEqual(calls[0][1], ("*IDN?",))
        self.assertEqual(calls[1][0], "write")
        instrument.close.assert_not_called()

    def test_wrong_device_is_closed_without_measurement_commands(self):
        instrument = Mock()
        instrument.query.return_value = "Other,Generator,123,1.0"
        manager = Mock()
        manager.open_resource.return_value = instrument
        with self.assertRaisesRegex(ValueError, "другой прибор"):
            open_instrument(manager, "TCPIP0::192.168.137.150::INSTR", True)
        instrument.write.assert_not_called()
        instrument.close.assert_called_once()

    def test_read_failure_closes_resource(self):
        instrument = Mock()
        instrument.query.side_effect = RuntimeError("timeout")
        manager = Mock()
        manager.open_resource.return_value = instrument
        with self.assertRaisesRegex(RuntimeError, "timeout"):
            open_instrument(manager, "TCPIP0::192.168.137.150::INSTR", True)
        instrument.write.assert_not_called()
        instrument.close.assert_called_once()

    def test_capture_is_matched_by_guid_before_any_windows_mutation(self):
        configurator = Mock()
        configurator.prepare.return_value = {"server_ip": "192.168.137.1"}
        interfaces = [
            {"guid": "{wifi}", "name": "Wi-Fi", "network_name": "wrong"},
            {"guid": "{WIRED}", "name": "Ethernet", "network_name": r"\Device\NPF_{WIRED}"},
        ]
        with patch("scapy.all.conf", SimpleNamespace(use_pcap=True)), \
                patch("scapy.arch.windows.get_windows_if_list", return_value=interfaces):
            plan = prepare_lan(configurator, "{wired}")
        self.assertEqual(plan["capture_interface"], r"\Device\NPF_{WIRED}")
        configurator.prepare.assert_called_once_with("{wired}")

    def test_missing_capture_adapter_does_not_change_network(self):
        configurator = Mock()
        with patch("scapy.all.conf", SimpleNamespace(use_pcap=True)), \
                patch("scapy.arch.windows.get_windows_if_list", return_value=[]):
            with self.assertRaises(RuntimeError):
                prepare_lan(configurator, "{wired}")
        configurator.prepare.assert_not_called()


if __name__ == "__main__":
    unittest.main()
