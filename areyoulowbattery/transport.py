import os
import sys
import glob
from typing import List, Dict, Optional, Tuple

if sys.platform != "win32":
    import fcntl
    import select

    IOC_READ = 2
    IOC_WRITE = 1

    def _IOC(dir_flag: int, type_char: str, nr: int, size: int) -> int:
        return (
            (dir_flag << 30)
            | ((size & 0x3FFF) << 16)
            | ((ord(type_char) & 0xFF) << 8)
            | (nr & 0xFF)
        )

    def HIDIOCSFEATURE(length: int) -> int:
        return _IOC(IOC_WRITE | IOC_READ, 'H', 0x06, length)

    def HIDIOCGFEATURE(length: int) -> int:
        return _IOC(IOC_WRITE | IOC_READ, 'H', 0x07, length)


class HidrawDevice:
    def __init__(self, dev_path: str, vendor_id: int, product_id: int, interface_number: Optional[int], name: str, usage_page: Optional[int] = None):
        self.dev_path = dev_path
        self.vendor_id = vendor_id
        self.product_id = product_id
        self.interface_number = interface_number
        self.name = name
        self.usage_page = usage_page

    def __repr__(self) -> str:
        return (f"<HidrawDevice {self.dev_path} {hex(self.vendor_id)}:{hex(self.product_id)} "
                f"iface={self.interface_number} page={hex(self.usage_page) if self.usage_page else None} name='{self.name}'>")


def enumerate_hidraw() -> List[HidrawDevice]:
    """Scans connected HID devices (via hidapi on Windows, sysfs /dev/hidraw on Linux)."""
    if sys.platform == "win32":
        try:
            import hid
            devices = []
            for d in hid.enumerate():
                raw_path = d.get('path', b'')
                dev_path = raw_path.decode('utf-8', errors='ignore') if isinstance(raw_path, bytes) else str(raw_path)
                vid = d.get('vendor_id', 0)
                pid = d.get('product_id', 0)
                upage = d.get('usage_page', None)
                iface = d.get('interface_number', None)
                if iface is None or iface == -1:
                    lower_path = dev_path.lower()
                    if "&mi_" in lower_path:
                        try:
                            sub = lower_path.split("&mi_")[1][:2]
                            iface = int(sub, 16)
                        except Exception:
                            pass
                name = d.get('product_string') or "Unknown"
                devices.append(HidrawDevice(dev_path, vid, pid, iface, name, usage_page=upage))

            # On Windows, sort so vendor collections (usage_page >= 0xFF00) come before standard collections
            devices.sort(key=lambda x: (x.usage_page or 0) >= 0xFF00, reverse=True)
            return devices
        except ImportError:
            return []

    devices = []
    for hidraw_entry in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        dev_name = os.path.basename(hidraw_entry)
        dev_path = f"/dev/{dev_name}"
        device_dir = os.path.join(hidraw_entry, "device")
        uevent_file = os.path.join(device_dir, "uevent")

        if not os.path.exists(uevent_file):
            continue

        vid = 0
        pid = 0
        name = "Unknown"
        with open(uevent_file, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("HID_ID="):
                    parts = line.split("=")[1].split(":")
                    if len(parts) >= 3:
                        try:
                            vid = int(parts[1], 16)
                            pid = int(parts[2], 16)
                        except ValueError:
                            pass
                elif line.startswith("HID_NAME="):
                    name = line.split("=", 1)[1]

        interface_number = None
        try:
            real_path = os.path.realpath(device_dir)
            parts = real_path.split("/")
            for part in parts:
                if ":" in part and "." in part:
                    subparts = part.split(":")
                    if len(subparts) == 2 and "." in subparts[1]:
                        interface_number = int(subparts[1].split(".")[1])
                        break
        except Exception:
            pass

        devices.append(HidrawDevice(dev_path, vid, pid, interface_number, name))
    return devices


class HidrawTransport:
    """Handles low-level read and write across Linux (/dev/hidraw) and Windows (hidapi)."""
    def __init__(self, dev_path: str, read_only: bool = False):
        self.dev_path = dev_path
        self.read_only = read_only
        self._fd: Optional[int] = None
        self._hid_device = None

    def open(self):
        if sys.platform == "win32":
            import hid
            self._hid_device = hid.device()
            path_bytes = self.dev_path.encode('utf-8') if isinstance(self.dev_path, str) else self.dev_path
            self._hid_device.open_path(path_bytes)
            self._hid_device.set_nonblocking(True)
            return

        if self._fd is None:
            mode = os.O_RDONLY if self.read_only else os.O_RDWR
            self._fd = os.open(self.dev_path, mode | os.O_NONBLOCK)

    def close(self):
        if self._hid_device is not None:
            try:
                self._hid_device.close()
            except Exception:
                pass
            self._hid_device = None

        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def send_feature_report(self, data: bytes):
        if sys.platform == "win32":
            if self._hid_device is None:
                raise RuntimeError("Device not open")
            self._hid_device.send_feature_report(list(data))
            return

        if self._fd is None:
            raise RuntimeError("Device not open")
        buf = bytearray(data)
        fcntl.ioctl(self._fd, HIDIOCSFEATURE(len(buf)), buf)

    def get_feature_report(self, report_id: int, length: int) -> bytes:
        if sys.platform == "win32":
            if self._hid_device is None:
                raise RuntimeError("Device not open")
            res = self._hid_device.get_feature_report(report_id, length)
            return bytes(res)

        if self._fd is None:
            raise RuntimeError("Device not open")
        buf = bytearray(length)
        buf[0] = report_id
        fcntl.ioctl(self._fd, HIDIOCGFEATURE(length), buf)
        return bytes(buf)

    def write_output_report(self, data: bytes):
        if sys.platform == "win32":
            if self._hid_device is None:
                raise RuntimeError("Device not open")
            self._hid_device.write(list(data))
            return

        if self._fd is None:
            raise RuntimeError("Device not open")
        os.write(self._fd, data)

    def read_input_report(self, length: int = 64, timeout_sec: float = 0.5) -> Optional[bytes]:
        if sys.platform == "win32":
            if self._hid_device is None:
                raise RuntimeError("Device not open")
            res = self._hid_device.read(length, timeout_ms=int(timeout_sec * 1000))
            if res:
                return bytes(res)
            return None

        if self._fd is None:
            raise RuntimeError("Device not open")
        r, _, _ = select.select([self._fd], [], [], timeout_sec)
        if r:
            return os.read(self._fd, length)
        return None
