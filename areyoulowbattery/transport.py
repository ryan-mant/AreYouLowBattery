import os
import glob
import fcntl
import select
from typing import List, Dict, Optional, Tuple

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
    def __init__(self, dev_path: str, vendor_id: int, product_id: int, interface_number: Optional[int], name: str):
        self.dev_path = dev_path
        self.vendor_id = vendor_id
        self.product_id = product_id
        self.interface_number = interface_number
        self.name = name

    def __repr__(self) -> str:
        return (f"<HidrawDevice {self.dev_path} {hex(self.vendor_id)}:{hex(self.product_id)} "
                f"iface={self.interface_number} name='{self.name}'>")

def enumerate_hidraw() -> List[HidrawDevice]:
    """Scans /sys/class/hidraw to identify connected devices, VIDs, PIDs and interfaces."""
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
                    # Format: HID_ID=0003:00001D57:0000FA65
                    parts = line.split("=")[1].split(":")
                    if len(parts) >= 3:
                        try:
                            vid = int(parts[1], 16)
                            pid = int(parts[2], 16)
                        except ValueError:
                            pass
                elif line.startswith("HID_NAME="):
                    name = line.split("=", 1)[1]

        # Extract interface number from sysfs path if available
        # Example device link: .../1-3.2:1.2/... -> interface 2
        interface_number = None
        try:
            real_path = os.path.realpath(device_dir)
            parts = real_path.split("/")
            for part in parts:
                if ":" in part and "." in part:
                    # Look for notation like 1-1:1.2
                    subparts = part.split(":")
                    if len(subparts) == 2 and "." in subparts[1]:
                        interface_number = int(subparts[1].split(".")[1])
                        break
        except Exception:
            pass

        devices.append(HidrawDevice(dev_path, vid, pid, interface_number, name))
    return devices

class HidrawTransport:
    """Handles low-level read and write on a /dev/hidraw node."""
    def __init__(self, dev_path: str, read_only: bool = False):
        self.dev_path = dev_path
        self.read_only = read_only
        self._fd: Optional[int] = None

    def open(self):
        if self._fd is None:
            mode = os.O_RDONLY if self.read_only else os.O_RDWR
            self._fd = os.open(self.dev_path, mode | os.O_NONBLOCK)

    def close(self):
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
        if self._fd is None:
            raise RuntimeError("Device not open")
        # In Linux, ioctl HIDIOCSFEATURE takes a buffer with report ID as first byte
        buf = bytearray(data)
        fcntl.ioctl(self._fd, HIDIOCSFEATURE(len(buf)), buf)

    def get_feature_report(self, report_id: int, length: int) -> bytes:
        if self._fd is None:
            raise RuntimeError("Device not open")
        buf = bytearray(length)
        buf[0] = report_id
        fcntl.ioctl(self._fd, HIDIOCGFEATURE(length), buf)
        return bytes(buf)

    def write_output_report(self, data: bytes):
        if self._fd is None:
            raise RuntimeError("Device not open")
        os.write(self._fd, data)

    def read_input_report(self, length: int = 64, timeout_sec: float = 0.5) -> Optional[bytes]:
        if self._fd is None:
            raise RuntimeError("Device not open")
        r, _, _ = select.select([self._fd], [], [], timeout_sec)
        if r:
            return os.read(self._fd, length)
        return None
