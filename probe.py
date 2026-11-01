"""
Diagnóstico: lista dispositivos Bluetooth pareados e verifica se expõem
o Battery Service padrão (GATT 0x180F / característica 0x2A19).

Uso (com o teclado LIGADO e CONECTADO via Bluetooth):
    python probe.py
"""
import asyncio
import uuid

from winrt.windows.devices.bluetooth import (
    BluetoothCacheMode,
    BluetoothDevice,
    BluetoothLEDevice,
)
from winrt.windows.devices.bluetooth.genericattributeprofile import (
    GattCommunicationStatus,
)
from winrt.windows.devices.enumeration import DeviceInformation
from winrt.windows.storage.streams import DataReader

BATTERY_SERVICE = uuid.UUID("0000180f-0000-1000-8000-00805f9b34fb")
BATTERY_LEVEL = uuid.UUID("00002a19-0000-1000-8000-00805f9b34fb")

KNOWN_SERVICES = {
    "1800": "Generic Access",
    "1801": "Generic Attribute",
    "180a": "Device Information",
    "180f": "Battery Service  <-- o que precisamos",
    "1812": "HID",
}


def short_uuid(u: uuid.UUID) -> str:
    return str(u)[4:8]


async def read_battery(service) -> str:
    chars = await service.get_characteristics_for_uuid_async(
        BATTERY_LEVEL, BluetoothCacheMode.UNCACHED
    )
    if chars.status != GattCommunicationStatus.SUCCESS or len(chars.characteristics) == 0:
        return f"característica 0x2A19 indisponível ({chars.status.name})"
    result = await chars.characteristics[0].read_value_async(BluetoothCacheMode.UNCACHED)
    if result.status != GattCommunicationStatus.SUCCESS:
        return f"falha na leitura ({result.status.name})"
    return f"{DataReader.from_buffer(result.value).read_byte()}%"


async def main() -> None:
    print("== Bluetooth Clássico (pareados) ==")
    classic = await DeviceInformation.find_all_async(
        BluetoothDevice.get_device_selector_from_pairing_state(True), []
    )
    for info in classic:
        print(f"  - {info.name}")
    if len(classic) == 0:
        print("  (nenhum)")

    print("\n== Bluetooth Low Energy (pareados) ==")
    le_devices = await DeviceInformation.find_all_async(
        BluetoothLEDevice.get_device_selector_from_pairing_state(True), []
    )
    if len(le_devices) == 0:
        print("  (nenhum)")

    for info in le_devices:
        print(f"\n  - {info.name}")
        dev = await BluetoothLEDevice.from_id_async(info.id)
        if dev is None:
            print("    não foi possível abrir o dispositivo")
            continue
        try:
            print(f"    conexão: {dev.connection_status.name}")
            res = await dev.get_gatt_services_async(BluetoothCacheMode.UNCACHED)
            if res.status != GattCommunicationStatus.SUCCESS:
                print(f"    falha ao listar serviços: {res.status.name}")
                continue
            for svc in res.services:
                code = short_uuid(svc.uuid)
                print(f"    serviço {code}: {KNOWN_SERVICES.get(code, str(svc.uuid))}")
                if svc.uuid == BATTERY_SERVICE:
                    print(f"      >> BATERIA: {await read_battery(svc)}")
                svc.close()
        finally:
            dev.close()


if __name__ == "__main__":
    asyncio.run(main())