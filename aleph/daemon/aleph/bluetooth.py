import asyncio
import dataclasses
import logging

from .util import spawn

log = logging.getLogger("aleph.bluetooth")

AUDIO_UUIDS = ("0000110b", "0000111e", "00001108", "0000110d")


@dataclasses.dataclass
class Device:
    path: str
    address: str
    name: str
    icon: str = ""
    paired: bool = False
    trusted: bool = False
    connected: bool = False
    uuids: tuple = ()
    rssi: int = None

    @property
    def is_audio(self):
        return self.icon.startswith("audio") or any(
            u.lower().startswith(AUDIO_UUIDS) for u in self.uuids)

    @property
    def kind(self):
        if self.is_audio:
            return "audio"
        if self.icon.startswith("input"):
            return "input"
        return "other"


class Backend:
    def __init__(self):
        self.devices = {}
        self.powered = False
        self.discovering = False
        self.address = ""
        self.listener = lambda kind, device, old: None

    def _emit(self, kind, device=None, old=None):
        self.listener(kind, device, old)


def _unwrap(value):
    if isinstance(value, (tuple, list)) and len(value) == 2 and type(value[0]).__name__ == "Signature":
        return _unwrap(value[1])
    if isinstance(value, dict):
        return {k: _unwrap(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_unwrap(v) for v in value)
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


class RavelBackend(Backend):
    """BlueZ over the system bus via dbussy/ravel, the binding ROCKNIX already ships."""

    async def start(self, listener):
        import dbussy
        import ravel
        self.listener = listener
        self._dbussy, self._ravel = dbussy, ravel
        self.bus = await ravel.system_bus_async(loop=asyncio.get_running_loop())
        self.adapter_path = None

        @ravel.signal(in_signature="oa{sa{sv}}")
        def added(path, interfaces, bus=None):
            self._apply(path, _unwrap(interfaces))

        @ravel.signal(in_signature="oas")
        def removed(path, interfaces, bus=None):
            if "org.bluez.Device1" in interfaces and path in self.devices:
                old = self.devices.pop(path)
                self._emit("removed", None, old)
            if "org.bluez.Adapter1" in interfaces and path == self.adapter_path:
                self.adapter_path = None
                self.powered = False
                self._emit("adapter")

        @ravel.signal(in_signature="sa{sv}as", message_keyword="message")
        def changed(interface, props, invalidated, message=None):
            self._apply(message.path, {interface: _unwrap(props)})

        self._handlers = (added, removed, changed)
        self.bus.listen_objects_added(added)
        self.bus.listen_objects_removed(removed)
        for iface in ("org.bluez.Device1", "org.bluez.Adapter1"):
            self.bus.listen_propchanged(path="/", fallback=True, interface=iface, func=changed)
        await self.refresh()

    async def refresh(self):
        try:
            om = await self.bus.get_proxy_object("org.bluez", "/").get_async_interface(
                self._dbussy.DBUSX.INTERFACE_OBJECT_MANAGER)
            objects = _unwrap((await om.GetManagedObjects())[0])
        except Exception as e:
            log.info("bluez not available: %s", e)
            self.powered = False
            self._emit("adapter")
            return
        for path, interfaces in objects.items():
            self._apply(path, interfaces)

    def _apply(self, path, interfaces):
        if "org.bluez.Adapter1" in interfaces:
            props = interfaces["org.bluez.Adapter1"]
            self.adapter_path = path
            self.powered = bool(props.get("Powered", self.powered))
            self.discovering = bool(props.get("Discovering", self.discovering))
            self.address = props.get("Address", self.address)
            self._emit("adapter")
        if "org.bluez.Device1" in interfaces:
            props = interfaces["org.bluez.Device1"]
            old = self.devices.get(path)
            dev = dataclasses.replace(old) if old else Device(path=path, address="", name="")
            for attr, key in (("address", "Address"), ("icon", "Icon"), ("paired", "Paired"),
                              ("trusted", "Trusted"), ("connected", "Connected"), ("rssi", "RSSI")):
                if key in props:
                    setattr(dev, attr, props[key])
            if "Alias" in props or "Name" in props:
                dev.name = props.get("Alias") or props.get("Name") or dev.address
            if "UUIDs" in props:
                dev.uuids = tuple(props["UUIDs"])
            if not dev.name:
                dev.name = dev.address
            self.devices[path] = dev
            self._emit("changed", dev, old)

    async def _iface(self, path, name):
        return await self.bus.get_proxy_object("org.bluez", path).get_async_interface(name)

    async def set_powered(self, on):
        if not self.adapter_path:
            await self.refresh()
        if self.adapter_path:
            adapter = await self._iface(self.adapter_path, "org.bluez.Adapter1")
            adapter.Powered = bool(on)
            await self._ravel.set_prop_flush(adapter)

    async def discover(self, on):
        if not self.adapter_path:
            return
        adapter = await self._iface(self.adapter_path, "org.bluez.Adapter1")
        try:
            await (adapter.StartDiscovery() if on else adapter.StopDiscovery())
        except Exception as e:
            log.info("discovery %s: %s", on, e)

    async def pair(self, path):
        dev = await self._iface(path, "org.bluez.Device1")
        try:
            await dev.Pair()
        except Exception as e:
            if "AlreadyExists" not in str(e):
                raise

    async def trust(self, path):
        dev = await self._iface(path, "org.bluez.Device1")
        dev.Trusted = True
        await self._ravel.set_prop_flush(dev)

    async def connect(self, path):
        await (await self._iface(path, "org.bluez.Device1")).Connect()

    async def disconnect(self, path):
        await (await self._iface(path, "org.bluez.Device1")).Disconnect()

    async def remove(self, path):
        adapter = await self._iface(self.adapter_path, "org.bluez.Adapter1")
        await adapter.RemoveDevice(path)


class FakeBackend(Backend):
    """Simulated radio for the development container."""

    def __init__(self):
        super().__init__()
        seeds = [
            ("AirPods Pro", "audio-headphones", True),
            ("8BitDo Pro 2", "input-gaming", True),
            ("Galaxy Buds2", "audio-headset", False),
            ("JBL Flip 6", "audio-card", False),
            ("iPhone", "phone", False),
        ]
        for i, (name, icon, paired) in enumerate(seeds):
            path = f"/org/bluez/hci0/dev_{i:02X}"
            self.devices[path] = Device(path, f"AA:BB:CC:DD:EE:{i:02X}", name, icon,
                                        paired=paired, trusted=paired, rssi=-40 - 9 * i)
        self.address = "AA:BB:CC:00:00:01"

    async def start(self, listener):
        self.listener = listener
        self.powered = True
        self._emit("adapter")

    async def _change(self, path, delay, **fields):
        await asyncio.sleep(delay)
        old = self.devices[path]
        self.devices[path] = dataclasses.replace(old, **fields)
        self._emit("changed", self.devices[path], old)

    async def set_powered(self, on):
        await asyncio.sleep(0.2)
        self.powered = bool(on)
        if not on:
            for path, dev in list(self.devices.items()):
                if dev.connected:
                    await self._change(path, 0, connected=False)
        self._emit("adapter")

    async def discover(self, on):
        discovering = bool(on) and self.powered
        if discovering != self.discovering:
            self.discovering = discovering
            self._emit("adapter")

    async def pair(self, path):
        await self._change(path, 1.2, paired=True)

    async def trust(self, path):
        await self._change(path, 0, trusted=True)

    async def connect(self, path):
        await self._change(path, 0.8, connected=True)

    async def disconnect(self, path):
        await self._change(path, 0.3, connected=False)

    async def remove(self, path):
        old = self.devices[path]
        self.devices[path] = dataclasses.replace(old, paired=False, trusted=False, connected=False)
        self._emit("changed", self.devices[path], old)


class Bluetooth:
    DISCOVERY_SECONDS = 45

    def __init__(self, backend, state, settings, t, events, system):
        self.backend = backend
        self.state = state
        self.settings = settings
        self.t = t
        self.events = events
        self.system = system
        self.busy = set()
        self._discovery_stop = None
        self._adapter_seen = None

    async def start(self):
        await self.backend.start(self._on_backend)
        self._publish()

    def _relevant(self, kind, device, old):
        if kind == "adapter":
            now = (self.backend.powered, self.backend.discovering)
            changed = now != self._adapter_seen
            self._adapter_seen = now
            return changed
        if kind == "changed" and device and old:
            return any(getattr(device, f) != getattr(old, f)
                       for f in ("name", "paired", "trusted", "connected", "icon"))
        return True

    def _on_backend(self, kind, device, old):
        if not self._relevant(kind, device, old):
            return
        if kind == "changed" and device and old and old.connected != device.connected:
            if device.connected:
                self.settings.remember_bluetooth(device.address, device.name)
                self.events.toast(self.t("bt_connected", name=device.name), "bluetooth")
            else:
                self.events.toast(self.t("bt_disconnected", name=device.name), "bluetooth")
                if device.is_audio:
                    self.events.audio_device_lost(device)
            if device.is_audio and device.connected:
                self.events.audio_device_found(device)
        self._publish()
        self.events.page_changed("/settings/bluetooth", "/control", "/settings")

    def _publish(self):
        audio = next((d.name for d in self.backend.devices.values()
                      if d.connected and d.is_audio), None)
        self.state.update("bluetooth", enabled=self.backend.powered, audio=audio,
                          discovering=self.backend.discovering)

    @property
    def enabled(self):
        return self.backend.powered

    def my_devices(self):
        devs = [d for d in self.backend.devices.values() if d.paired]
        return sorted(devs, key=lambda d: (not d.connected, d.name.casefold()))

    def other_devices(self):
        devs = [d for d in self.backend.devices.values()
                if not d.paired and d.name and d.name != d.address]
        return sorted(devs, key=lambda d: -(d.rssi if d.rssi is not None else -200))

    def recent_audio(self):
        known = {d.address: d for d in self.backend.devices.values() if d.paired}
        out = []
        for entry in self.settings["recent_bluetooth"]:
            dev = known.get(entry["address"])
            if dev and dev.is_audio:
                out.append(dev)
        for dev in self.my_devices():
            if dev.is_audio and dev not in out:
                out.append(dev)
        return out[:3]

    def find(self, path):
        return self.backend.devices.get(path)

    async def set_enabled(self, on):
        await self.system.set_bluetooth(on)
        if on:
            await self._wait_for_adapter()
        try:
            await self.backend.set_powered(on)
        except Exception as e:
            log.warning("set powered failed: %s", e)
        self._publish()

    async def _wait_for_adapter(self):
        refresh = getattr(self.backend, "refresh", None)
        for _ in range(10):
            if refresh:
                await refresh()
            if getattr(self.backend, "adapter_path", True):
                return
            await asyncio.sleep(0.5)

    def begin_discovery(self):
        if not self.backend.powered:
            return
        if not self.backend.discovering:
            spawn(self.backend.discover(True))
        if self._discovery_stop:
            self._discovery_stop.cancel()
        self._discovery_stop = asyncio.get_running_loop().call_later(
            self.DISCOVERY_SECONDS, lambda: spawn(self.backend.discover(False)))

    def end_discovery(self):
        if self._discovery_stop:
            self._discovery_stop.cancel()
            self._discovery_stop = None
        spawn(self.backend.discover(False))

    async def activate(self, path):
        dev = self.find(path)
        if not dev or path in self.busy:
            return
        self.busy.add(path)
        self.events.page_changed("/settings/bluetooth", "/control")
        try:
            if dev.connected:
                await self.backend.disconnect(path)
            else:
                if not dev.paired:
                    await self.backend.discover(False)
                    await self.backend.pair(path)
                if not self.find(path).trusted:
                    await self.backend.trust(path)
                await self._connect_with_retry(path)
        except Exception as e:
            log.warning("bluetooth action failed: %s", e)
            self.events.toast(self.t("bt_failed", name=dev.name), "bluetooth")
        finally:
            self.busy.discard(path)
            self.events.page_changed("/settings/bluetooth", "/control")

    async def _connect_with_retry(self, path, attempts=3):
        for attempt in range(attempts):
            try:
                await self.backend.connect(path)
                return
            except Exception:
                if attempt == attempts - 1:
                    raise
                await asyncio.sleep(1.0)

    async def forget(self, path):
        dev = self.find(path)
        if not dev:
            return
        await self.backend.remove(path)
        self.settings.forget_bluetooth(dev.address)
        self.events.toast(self.t("forgot_device"), "bluetooth")
