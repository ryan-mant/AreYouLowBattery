"""
Automated udev rules installer for Linux systems (pkexec / Polkit).
Completely bypassed and invisible on Windows.
"""

import os
import sys
import shutil
import subprocess
import tempfile
from typing import Optional

from areyoulowbattery.i18n import tr
from areyoulowbattery.profile_loader import get_resource_dir
from areyoulowbattery.clean_env import get_clean_env
from areyoulowbattery.logger import logger


TARGET_RULES_PATH = "/etc/udev/rules.d/99-areyoulowbattery.rules"
FALLBACK_SYSTEM_RULES_PATH = "/usr/lib/udev/rules.d/99-areyoulowbattery.rules"


def _active_rule_lines(text: str) -> set:
    """Returns the normalized, non-comment rule lines of a udev rules file."""
    lines = set()
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if line and not line.startswith("#"):
            lines.add(line)
    return lines


def are_udev_rules_installed() -> bool:
    """Returns True if the installed udev rules contain every rule of the bundled file (Linux only)."""
    if not sys.platform.startswith("linux"):
        return True

    installed_path = None
    if os.path.exists(TARGET_RULES_PATH):
        installed_path = TARGET_RULES_PATH
    elif os.path.exists(FALLBACK_SYSTEM_RULES_PATH):
        installed_path = FALLBACK_SYSTEM_RULES_PATH

    if not installed_path:
        return False

    try:
        with open(installed_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        bundled_path = get_rules_source_path()
        if not bundled_path:
            # Bundled rules not found: fall back to the minimal hardening check.
            return "1d57" in content and "25a7" in content and "046d" in content

        with open(bundled_path, "r", encoding="utf-8", errors="ignore") as f:
            required = _active_rule_lines(f.read())

        missing = required - _active_rule_lines(content)
        if missing:
            logger.debug("Installed udev rules at %s are outdated (%d rule(s) missing)", installed_path, len(missing))
            return False
        return True
    except Exception as e:
        logger.debug("Failed to read udev rules at %s: %s", installed_path, e)

    return False


def get_rules_source_path() -> Optional[str]:
    """Finds the bundled 99-areyoulowbattery.rules or creates a temporary copy."""
    src = os.path.join(get_resource_dir(), "rules", "99-areyoulowbattery.rules")
    if os.path.exists(src):
        return src

    # Alternative paths (repository root / local install)
    alt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rules", "99-areyoulowbattery.rules")
    if os.path.exists(alt):
        return alt

    return None


def install_udev_rules(parent=None) -> bool:
    """
    Installs the 99-areyoulowbattery.rules using pkexec graphical authorization.
    Never runs on Windows. Returns True on success, False if canceled or failed.
    """
    if not sys.platform.startswith("linux"):
        return False

    from PySide6.QtWidgets import QMessageBox

    rules_src = get_rules_source_path()
    if not rules_src or not os.path.exists(rules_src):
        if parent:
            QMessageBox.critical(
                parent,
                tr("udev.error.title"),
                tr("udev.error.rules_missing"),
            )
        return False

    pkexec_path = shutil.which("pkexec")
    if not pkexec_path:
        if parent:
            QMessageBox.warning(
                parent,
                tr("udev.pkexec_missing.title"),
                tr("udev.pkexec_missing.body", rules_src=rules_src, target=TARGET_RULES_PATH),
            )
        return False

    # Prefer standalone helper script if present, otherwise direct install binary
    script_path = os.path.join(get_resource_dir(), "rules", "install_udev.sh")
    if not os.path.exists(script_path):
        script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rules", "install_udev.sh")

    if os.path.exists(script_path):
        pkexec_cmd = ["pkexec", script_path, rules_src]
    else:
        # Fallback to direct install binary invocation without shell interpolation
        pkexec_cmd = ["pkexec", "/usr/bin/install", "-m", "0644", rules_src, TARGET_RULES_PATH]

    try:
        proc = subprocess.run(
            pkexec_cmd,
            env=get_clean_env(),
            capture_output=True,
            text=True,
            timeout=60,
        )

        if proc.returncode == 0:
            # If we used fallback, reload udev
            if pkexec_cmd[1] != script_path:
                try:
                    subprocess.run(["udevadm", "control", "--reload"], env=get_clean_env(), timeout=5)
                    subprocess.run(["udevadm", "trigger"], env=get_clean_env(), timeout=5)
                except Exception:
                    pass

            if parent:
                QMessageBox.information(
                    parent,
                    tr("udev.success.title"),
                    tr("udev.success.body"),
                )
            return True
        elif proc.returncode == 126:
            # User dismissed the graphical authentication prompt
            logger.info("udev rule installation canceled by user (exit code 126)")
            return False
        elif proc.returncode == 127:
            # Not authorized: wrong password, polkit denied, or no authentication agent running
            err = proc.stderr.strip() or proc.stdout.strip() or "Not authorized"
            logger.warning("pkexec udev rule install not authorized: %s", err)
            if parent:
                QMessageBox.warning(
                    parent,
                    tr("udev.auth_failed.title"),
                    tr("udev.auth_failed.body", rules_src=rules_src, target=TARGET_RULES_PATH),
                )
            return False
        else:
            err = proc.stderr.strip() or proc.stdout.strip() or f"Process exited with code {proc.returncode}"
            logger.warning("pkexec udev rule install failed: %s", err)
            if parent:
                QMessageBox.warning(
                    parent,
                    tr("udev.install_failed.title"),
                    tr("udev.install_failed.body", error=err),
                )
            return False

    except subprocess.TimeoutExpired:
        logger.warning("pkexec udev installation timed out")
        return False
    except Exception as e:
        logger.exception("Error executing pkexec udev installation")
        if parent:
            QMessageBox.critical(parent, tr("udev.error.title"), tr("udev.exec_failed.body", e=e))
        return False
