import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import network_utils as network


def adapter(guid="wired", ip="169.254.150.200", mask="255.255.0.0", **values):
    result = {
        "guid": guid, "index": 19, "name": "Ethernet", "description": "Test Ethernet",
        "ethernet": True, "connected": True, "dhcp": True,
        "addresses": [{"ip": ip, "mask": mask}], "gateways": [],
    }
    result.update(values)
    return result


class LanPlanTests(unittest.TestCase):
    def test_apipa_gets_dedicated_subnet_without_selecting_wifi(self):
        wired = adapter()
        wifi = adapter("wifi", "172.20.133.81", "255.255.255.0", ethernet=False)
        plan = network.build_lan_plan(wired, [wired, wifi])
        self.assertEqual(plan["adapter"]["guid"], "wired")
        self.assertEqual(plan["server_ip"], "192.168.137.1")
        self.assertEqual(plan["pool_start"], "192.168.137.150")
        self.assertTrue(plan["change"])
        with self.assertRaises(ValueError):
            network.build_lan_plan(wifi, [wired, wifi])

    def test_occupied_subnet_is_skipped_even_on_virtual_adapter(self):
        wired = adapter()
        virtual = adapter("hyperv", "192.168.137.1", "255.255.255.0", ethernet=False)
        plan = network.build_lan_plan(wired, [wired, virtual])
        self.assertEqual(plan["server_ip"], "192.168.50.1")

    def test_existing_static_subnet_is_reused(self):
        wired = adapter(ip="10.10.5.2", mask="255.255.255.0", dhcp=False)
        plan = network.build_lan_plan(wired, [wired])
        self.assertFalse(plan["change"])
        self.assertEqual(plan["server_ip"], "10.10.5.2")
        self.assertEqual(plan["pool_start"], "10.10.5.150")

    def test_small_subnet_pool_stays_inside_network(self):
        wired = adapter(ip="192.168.10.9", mask="255.255.255.248")
        plan = network.build_lan_plan(wired, [wired])
        self.assertEqual(plan["pool_start"], "192.168.10.10")
        self.assertEqual(plan["pool_end"], "192.168.10.14")

    def test_unplugged_adapter_cannot_be_configured(self):
        wired = adapter(connected=False)
        with self.assertRaises(ValueError):
            network.build_lan_plan(wired, [wired])


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.configurator = network.LanConfigurator(Path(self.directory.name) / "backup.json")
        self.original = adapter()

    def test_backup_is_written_before_configuration_and_guid_survives_index_change(self):
        current = copy.deepcopy(self.original)
        calls = []

        def command(arguments):
            self.assertTrue(self.configurator.has_backup())
            self.assertEqual(
                json.loads(self.configurator.backup_path.read_text(encoding="utf-8")),
                self.original)
            calls.append(arguments)
            if "source=static" in arguments:
                current["dhcp"] = False
                current["addresses"] = [{"ip": "192.168.137.1", "mask": "255.255.255.0"}]
            else:
                current["dhcp"] = True

        with patch.object(network, "list_adapters", side_effect=lambda: [copy.deepcopy(current)]), \
                patch.object(network, "_netsh", side_effect=command):
            self.configurator.prepare("wired")
            current["index"] = 42
            self.configurator.restore()
        self.assertIn("name=19", calls[0])
        self.assertIn("name=42", calls[1])
        self.assertFalse(self.configurator.has_backup())
        self.assertTrue(all("dns" not in " ".join(call).lower() for call in calls))

    def test_failed_assignment_rolls_back_dhcp(self):
        calls = []

        def command(arguments):
            calls.append(arguments)
            if "source=static" in arguments:
                raise RuntimeError("assignment failed")

        with patch.object(network, "list_adapters", return_value=[self.original]), \
                patch.object(network, "_netsh", side_effect=command):
            with self.assertRaisesRegex(RuntimeError, "assignment failed"):
                self.configurator.prepare("wired")
        self.assertIn("source=dhcp", calls[-1])
        self.assertFalse(self.configurator.has_backup())

    def test_failed_rollback_keeps_recovery_file(self):
        with patch.object(network, "list_adapters", return_value=[self.original]), \
                patch.object(network, "_netsh", side_effect=RuntimeError("access denied")):
            with self.assertRaisesRegex(RuntimeError, "Откат не завершён"):
                self.configurator.prepare("wired")
        self.assertTrue(self.configurator.has_backup())

    def test_pending_backup_prevents_second_mutation(self):
        self.configurator._save(self.original)
        with patch.object(network, "list_adapters", return_value=[self.original]), \
                patch.object(network, "_netsh") as command:
            with self.assertRaises(ValueError):
                self.configurator.prepare("wired")
        command.assert_not_called()

    def test_reuse_does_not_write_backup_or_change_settings(self):
        wired = adapter(ip="192.168.50.2", mask="255.255.255.0", dhcp=False)
        with patch.object(network, "list_adapters", return_value=[wired]), \
                patch.object(network, "_netsh") as command:
            self.configurator.prepare("wired")
        command.assert_not_called()
        self.assertFalse(self.configurator.has_backup())

    def test_missing_adapter_keeps_backup(self):
        self.configurator._save(self.original)
        with patch.object(network, "list_adapters", return_value=[]), \
                patch.object(network, "_netsh") as command:
            with self.assertRaises(RuntimeError):
                self.configurator.restore()
        command.assert_not_called()
        self.assertTrue(self.configurator.has_backup())


if __name__ == "__main__":
    unittest.main()
