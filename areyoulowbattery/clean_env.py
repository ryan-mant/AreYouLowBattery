import os

def get_clean_env() -> dict:
    """
    Returns a copy of os.environ with PyInstaller's LD_LIBRARY_PATH removed or
    restored to LD_LIBRARY_PATH_ORIG. This prevents system binaries (like systemctl,
    udevadm, bluetoothctl, pw-play) from loading bundled older shared libraries (like libcrypto.so.3).
    """
    env = os.environ.copy()
    if "LD_LIBRARY_PATH_ORIG" in env:
        env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH_ORIG"]
    else:
        env.pop("LD_LIBRARY_PATH", None)
    return env
