"""Windows LAN configuration. All commands target a selected physical Ethernet GUID."""

import base64
import json
import os
import subprocess
from ipaddress import IPv4Address, IPv4Interface, IPv4Network
from pathlib import Path


def run_powershell(script):
    wrapped = (
        "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; "
        "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)\n"
        "try {\n" + script + "\n} catch {\n"
        "ConvertTo-Json -Compress -InputObject @{error=$_.Exception.Message}; exit 1\n}"
    )
    encoded = base64.b64encode(wrapped.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, timeout=45,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    output = result.stdout.decode("utf-8-sig", errors="replace").strip()
    if result.returncode:
        error = result.stderr.decode("utf-8-sig", errors="replace").strip()
        try:
            message = json.loads(output)["error"]
        except (ValueError, KeyError, TypeError):
            message = output or error or "Ошибка настройки сети Windows."
        raise RuntimeError(message)
    return json.loads(output) if output else None


def list_adapters():
    # Win32_NetworkAdapter.AdapterTypeID can incorrectly label Wi-Fi as Ethernet.
    # Use the NDIS physical medium instead (14 = 802.3).
    result = run_powershell(r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$configs = @(Get-CimInstance Win32_NetworkAdapterConfiguration)
$ethernetGuids = @(Get-NetAdapter -Physical | Where-Object {
    $_.NdisPhysicalMedium -eq 14
} | ForEach-Object { $_.InterfaceGuid.ToString().Trim('{}').ToLowerInvariant() })
$items = @(Get-CimInstance Win32_NetworkAdapter | ForEach-Object {
    $adapter = $_
    $config = $configs | Where-Object { $_.Index -eq $adapter.Index } | Select-Object -First 1
    $addresses = @()
    if ($config -and $config.IPAddress -and $config.IPSubnet) {
        for ($i = 0; $i -lt @($config.IPAddress).Count; $i++) {
            if ($config.IPAddress[$i] -notmatch ':') {
                $addresses += @{ip=$config.IPAddress[$i]; mask=$config.IPSubnet[$i]}
            }
        }
    }
    [pscustomobject]@{
        guid=$adapter.GUID; index=$adapter.InterfaceIndex
        name=$adapter.NetConnectionID; description=$adapter.Name
        ethernet=($null -ne $adapter.GUID -and $ethernetGuids -contains $adapter.GUID.Trim('{}').ToLowerInvariant())
        connected=($adapter.NetConnectionStatus -eq 2)
        dhcp=[bool]$config.DHCPEnabled
        addresses=@($addresses)
        gateways=@($config.DefaultIPGateway | Where-Object { $_ -and $_ -notmatch ':' })
        gateway_metrics=@($config.GatewayCostMetric)
    }
})
ConvertTo-Json -InputObject $items -Depth 6 -Compress
""")
    return result or []


def build_lan_plan(selected, adapters):
    if not selected["ethernet"]:
        raise ValueError("Выберите физический Ethernet-адаптер.")
    if not selected["connected"]:
        raise ValueError("Ethernet-кабель не подключён. Подключите прибор и обновите список.")
    other_networks = []
    for adapter in adapters:
        if adapter["guid"] == selected["guid"]:
            continue
        for address in adapter["addresses"]:
            other_networks.append(IPv4Interface(f"{address['ip']}/{address['mask']}").network)

    # Reuse a routable existing IPv4 network if it cannot select another NIC.
    for address in selected["addresses"]:
        interface = IPv4Interface(f"{address['ip']}/{address['mask']}")
        ip = interface.ip
        if (ip.is_link_local or ip.is_loopback or ip.is_unspecified
                or ip.is_multicast or interface.network.prefixlen > 29
                or ip in {interface.network.network_address, interface.network.broadcast_address}):
            continue
        if any(interface.network.overlaps(net) for net in other_networks):
            continue
        return _make_plan(selected, interface, change=False)

    # Keep all other adapters, including Wi-Fi and Hyper-V, outside this subnet.
    for third_octet in (137, 50, 51, 52, 53, 54, 55):
        interface = IPv4Interface(f"192.168.{third_octet}.1/24")
        if not any(interface.network.overlaps(net) for net in other_networks):
            if selected["gateways"]:
                raise ValueError(
                    "У выбранного Ethernet есть шлюз и конфликтующая подсеть. "
                    "Выберите отдельный адаптер для прямого подключения мультиметра."
                )
            return _make_plan(selected, interface, change=True)
    raise ValueError("Не удалось подобрать отдельную подсеть для Ethernet.")


def _make_plan(adapter, interface, change):
    network = interface.network
    max_host = network.num_addresses - 2
    start = min(150, max(1, max_host - 50))
    end = min(200, max_host)
    excluded = {str(interface.ip), *adapter["gateways"]}
    free = [str(IPv4Address(int(network.network_address) + offset))
            for offset in range(start, end + 1)
            if str(IPv4Address(int(network.network_address) + offset)) not in excluded]
    if not free:
        raise ValueError("В подсети нет свободного места для пула DHCP.")
    return {
        "adapter": adapter, "server_ip": str(interface.ip),
        "mask": str(network.netmask), "pool_start": free[0], "pool_end": free[-1],
        "gateway": next((gw for gw in adapter["gateways"]
                         if IPv4Address(gw) in network), ""),
        "change": change,
    }


def _netsh(arguments):
    result = subprocess.run(
        ["netsh.exe", "interface", "ipv4", *arguments],
        capture_output=True, timeout=40,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        # netsh uses the Windows OEM codepage.
        import ctypes
        encoding = f"cp{ctypes.windll.kernel32.GetOEMCP()}"
        message = (result.stdout + result.stderr).decode(encoding, errors="replace").strip()
        raise RuntimeError(message or "Не удалось изменить IPv4. Нужны права администратора.")


class LanConfigurator:
    def __init__(self, backup_path=None):
        self.backup_path = Path(backup_path or Path(__file__).with_name(".lan_restore.json"))

    def has_backup(self):
        return self.backup_path.exists()

    def _save(self, adapter):
        temporary = self.backup_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(adapter, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.backup_path)

    def prepare(self, guid):
        adapters = list_adapters()
        selected = next((a for a in adapters if a["guid"] == guid), None)
        if selected is None:
            raise ValueError("Выбранный адаптер отключён или удалён.")
        if self.has_backup():
            raise ValueError("Сначала восстановите предыдущие настройки Ethernet.")
        plan = build_lan_plan(selected, adapters)
        if not plan["change"]:
            return plan
        # Persist before the first mutation, so a crash cannot lose the original.
        self._save(selected)
        try:
            _netsh([
                "set", "address", f"name={selected['index']}", "source=static",
                f"address={plan['server_ip']}", f"mask={plan['mask']}",
                "gateway=none", "store=persistent",
            ])
            self._verify_address(guid, plan["server_ip"])
        except Exception as exc:
            try:
                self.restore()
            except Exception as rollback:
                raise RuntimeError(
                    f"{exc}\nОткат не завершён: {rollback}\n"
                    "Исходные настройки сохранены. Нажмите «Восстановить Ethernet»."
                ) from exc
            raise
        return plan

    @staticmethod
    def _verify_address(guid, expected):
        import time
        for _ in range(5):
            selected = next((a for a in list_adapters() if a["guid"] == guid), None)
            if selected and any(a["ip"] == expected for a in selected["addresses"]):
                return
            time.sleep(0.4)
        raise RuntimeError(f"Windows не подтвердила установку адреса {expected}.")

    def restore(self):
        if not self.has_backup():
            return
        original = json.loads(self.backup_path.read_text(encoding="utf-8"))
        # Resolve GUID again: interface indexes can change after reboot.
        current = next((a for a in list_adapters() if a["guid"] == original["guid"]), None)
        if current is None or not current["ethernet"]:
            raise RuntimeError("Исходный Ethernet-адаптер недоступен. Резервная копия сохранена.")
        name = f"name={current['index']}"
        if original["dhcp"]:
            _netsh(["set", "address", name, "source=dhcp", "store=persistent"])
        else:
            addresses = original["addresses"]
            if not addresses:
                raise RuntimeError("В резервной копии нет исходного статического IPv4.")
            gateways = original["gateways"]
            _netsh([
                "set", "address", name, "source=static",
                f"address={addresses[0]['ip']}", f"mask={addresses[0]['mask']}",
                f"gateway={gateways[0] if gateways else 'none'}", "store=persistent",
            ])
            for address in addresses[1:]:
                _netsh(["add", "address", name, f"address={address['ip']}",
                        f"mask={address['mask']}", "store=persistent"])
            # Configuration requiring replacement is rejected if it has a gateway;
            # this also supports reading a saved configuration from an earlier run.
            for gateway in gateways[1:]:
                _netsh(["add", "route", "prefix=0.0.0.0/0",
                        f"interface={current['index']}", f"nexthop={gateway}",
                        "store=persistent"])
        import time
        for _ in range(5):
            restored = next((a for a in list_adapters()
                             if a["guid"] == original["guid"]), None)
            if restored and restored["dhcp"] == original["dhcp"]:
                if original["dhcp"] or all(
                        address in restored["addresses"] for address in original["addresses"]):
                    break
            time.sleep(0.4)
        else:
            raise RuntimeError(
                "Windows ещё не подтвердила восстановление IPv4. "
                "Резервная копия сохранена; повторите восстановление.")
        # DNS is never changed by this application.
        self.backup_path.unlink()
