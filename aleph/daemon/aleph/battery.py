import asyncio
import glob
import logging
import os

log = logging.getLogger("aleph.battery")

SMOOTHED = "/tmp/battery.percent"


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


class Battery:
    """Percent from batteryplus when present (the PMIC gauge is uncalibrated on mainline)."""

    INTERVAL = 30

    def __init__(self, state, sim=False, root="/sys/class/power_supply"):
        self.state = state
        self.sim = sim
        self.root = root

    async def start(self):
        if self.sim:
            self.state.update("battery", percent=78, charging=False)
            return
        self.refresh()
        try:
            import pyudev
            monitor = pyudev.Monitor.from_netlink(pyudev.Context())
            monitor.filter_by("power_supply")
            monitor.start()
            asyncio.get_running_loop().add_reader(monitor.fileno(), self._uevent, monitor)
        except ImportError:
            pass
        asyncio.ensure_future(self._poll())

    def _uevent(self, monitor):
        while monitor.poll(timeout=0) is not None:
            pass
        self.refresh()

    async def _poll(self):
        while True:
            await asyncio.sleep(self.INTERVAL)
            self.refresh()

    def refresh(self):
        battery = next((d for d in sorted(glob.glob(os.path.join(self.root, "*")))
                        if _read(os.path.join(d, "type")) == "Battery"), None)
        if not battery:
            return
        percent = _read(SMOOTHED) or _read(os.path.join(battery, "capacity")) or "0"
        status = _read(os.path.join(battery, "status")) or ""
        try:
            value = max(0, min(100, int(float(percent))))
        except ValueError:
            value = 0
        self.state.update("battery", percent=value, charging=status in ("Charging", "Full"))
