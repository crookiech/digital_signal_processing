import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication

import main_window
from network_utils import build_lan_plan
from test_network_utils import adapter


class LanUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"
        if font_path.exists():
            QFontDatabase.addApplicationFont(str(font_path))
            cls.app.setFont(QFont("Segoe UI", 9))

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.original = adapter()
        self.wifi = adapter("wifi", "172.20.133.81", "255.255.255.0", ethernet=False)
        self.configurator = Mock()
        self.configurator.has_backup.return_value = False
        self.settings = QSettings(
            str(Path(self.directory.name) / "settings.ini"), QSettings.Format.IniFormat)
        self.manager = Mock()
        self.manager.list_resources.return_value = []
        self.patchers = [
            patch.object(main_window, "LanConfigurator", return_value=self.configurator),
            patch.object(main_window, "QSettings", return_value=self.settings),
            patch.object(main_window, "list_adapters", return_value=[self.original, self.wifi]),
            patch.object(main_window.pyvisa, "ResourceManager", return_value=self.manager),
            patch.object(main_window.QMessageBox, "warning"),
            patch.object(main_window.QMessageBox, "information"),
        ]
        for patcher in self.patchers:
            patcher.start()
        self.addCleanup(self.cleanup_window)
        self.window = main_window.MultimeterApp()
        self.window.radio_lan.setChecked(True)
        self.window.show()
        self.wait_operation()

    def wait_operation(self):
        deadline = time.monotonic() + 5
        # Initial refresh is scheduled by a zero timer.
        self.app.processEvents()
        while self.window.operation is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertIsNone(self.window.operation, "GUI worker did not finish")

    def cleanup_window(self):
        if hasattr(self, "window"):
            self.wait_operation()
            self.configurator.has_backup.return_value = False
            self.window.close()
            self.app.processEvents()
        for patcher in reversed(self.patchers):
            patcher.stop()

    def server(self, leases):
        server = Mock()
        server.error = None
        server.running = True
        server.is_alive.return_value = True
        server.get_leases.return_value = leases
        return server

    def test_wifi_is_excluded_and_single_connected_ethernet_is_selected(self):
        self.assertEqual(self.window.adapter_combo.count(), 1)
        self.assertEqual(self.window.adapter_combo.currentData(), "wired")

    def test_prepare_populates_pc_fields_and_lease_populates_device_field(self):
        plan = build_lan_plan(self.original, [self.original, self.wifi])
        plan["capture_interface"] = "capture-wired"
        server = self.server({})
        with patch.object(main_window, "prepare_lan", return_value=plan), \
                patch.object(main_window, "MiniDhcpServer", return_value=server):
            self.window.toggle_dhcp_server()
            self.wait_operation()
        self.assertEqual(self.window.pc_ip_edit.text(), "192.168.137.1")
        self.assertEqual(self.window.ip_edit.text(), "")
        self.assertFalse(self.window.adapter_combo.isEnabled())
        server.get_leases.return_value = {"aa:bb:cc:dd:ee:01": "192.168.137.150"}
        self.window.check_dhcp_status()
        self.assertEqual(self.window.ip_edit.text(), "192.168.137.150")
        self.assertEqual(self.window.lease_combo.count(), 1)
        # A second refresh must not overwrite a manually entered device address.
        self.window.ip_edit.setText("192.168.137.160")
        self.window.check_dhcp_status()
        self.assertEqual(self.window.ip_edit.text(), "192.168.137.160")

    def test_multiple_initial_leases_require_explicit_selection(self):
        self.window.dhcp_server = self.server({
            "aa:bb:cc:dd:ee:01": "192.168.137.150",
            "aa:bb:cc:dd:ee:02": "192.168.137.151",
        })
        self.window.check_dhcp_status()
        self.assertEqual(self.window.lease_combo.currentIndex(), -1)
        self.assertEqual(self.window.ip_edit.text(), "")
        self.window.lease_combo.setCurrentIndex(1)
        self.assertEqual(self.window.ip_edit.text(), "192.168.137.151")

    def test_lan_connect_checks_identity_and_enables_measurements(self):
        self.window.ip_edit.setText("192.168.137.150")
        instrument = Mock()
        with patch.object(main_window, "open_instrument",
                          return_value=(instrument, "UNI-T,UT8805E,123,1.0")) as opener:
            self.window.toggle_connection()
            self.wait_operation()
        self.assertTrue(opener.call_args.kwargs["require_ut8805e"])
        self.assertTrue(self.window.is_connected)
        self.assertTrue(self.window.btn_start.isEnabled())
        self.assertFalse(self.window.ip_edit.isEnabled())
        self.window.disconnect_instrument()
        instrument.close.assert_called_once()
        self.assertFalse(self.window.btn_start.isEnabled())

    def test_failed_dhcp_restores_config_and_clears_prepared_state(self):
        self.window.lan_plan = build_lan_plan(self.original, [self.original])
        server = self.server({})
        server.error = "Npcap failed"
        self.window.dhcp_server = server
        self.window.check_dhcp_status()
        self.wait_operation()
        self.configurator.restore.assert_called_once()
        self.assertIsNone(self.window.lan_plan)
        self.assertIsNone(self.window.dhcp_server)

    def test_dhcp_failure_disconnects_instrument_before_restoring_ethernet(self):
        instrument = Mock()
        self.window.instrument = instrument
        self.window.is_connected = True
        server = self.server({})
        server.error = "capture failed"
        self.window.dhcp_server = server
        self.window.check_dhcp_status()
        self.wait_operation()
        instrument.close.assert_called_once()
        self.assertFalse(self.window.is_connected)
        self.configurator.restore.assert_called_once()

    def test_close_restores_saved_configuration_before_exiting(self):
        self.configurator.has_backup.return_value = True
        self.configurator.restore.side_effect = (
            lambda: setattr(self.configurator.has_backup, "return_value", False))
        self.window.close()
        self.wait_operation()
        self.configurator.restore.assert_called_once()
        self.assertFalse(self.window.isVisible())


if __name__ == "__main__":
    unittest.main()
