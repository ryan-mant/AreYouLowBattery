"""
Lightweight internationalization (i18n) layer for AreYouLowBattery.

Supported languages:
  - en_US (English - United States) - default / fallback
  - pt_BR (Portuguese - Brazil)

The user selected language is persisted inside ``settings.json`` in the
per-user configuration directory:

  - Linux:   ``~/.config/areyoulowbattery/settings.json``
             (or ``$XDG_CONFIG_HOME/areyoulowbattery/settings.json``)
  - Windows: ``%LOCALAPPDATA%\\areyoulowbattery\\settings.json``

The ``AREYOULOWBATTERY_CONFIG_DIR`` environment variable overrides the whole
configuration directory (handy for tests and portable installs).
"""

import json
import os
import sys
from typing import Dict

DEFAULT_LANGUAGE = "en_US"

SUPPORTED_LANGUAGES = [
    ("en_US", "English (US)"),
    ("pt_BR", "Português (Brasil)"),
]

_LANGUAGE_CODES = [code for code, _label in SUPPORTED_LANGUAGES]

SETTINGS_FILENAME = "settings.json"


def get_config_dir() -> str:
    """Returns the per-user configuration directory (never raises)."""
    override = os.environ.get("AREYOULOWBATTERY_CONFIG_DIR")
    if override:
        directory = os.path.expanduser(override)
    else:
        if sys.platform == "win32":
            base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        else:
            base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        directory = os.path.join(base, "areyoulowbattery")
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError:
        pass
    return directory


def get_settings_path() -> str:
    """Absolute path of the persisted settings.json file."""
    return os.path.join(get_config_dir(), SETTINGS_FILENAME)


def _read_settings() -> dict:
    path = get_settings_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def _write_settings(settings: dict) -> None:
    import tempfile

    path = get_settings_path()
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=".settings_", suffix=".tmp", dir=os.path.dirname(path) or ".")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
        tmp_path = None
    except OSError:
        # Never let a read-only config dir break the UI.
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Language state
# ---------------------------------------------------------------------------

_loaded_path = None
_current_language = DEFAULT_LANGUAGE


def _read_language_from_disk() -> str:
    lang = _read_settings().get("language")
    if isinstance(lang, str) and lang in _LANGUAGE_CODES:
        return lang
    return DEFAULT_LANGUAGE


def get_language() -> str:
    """Returns the active language code ('en_US' or 'pt_BR').

    The settings file is only parsed once per configuration directory; call
    :func:`set_language` to change it at runtime.
    """
    global _loaded_path, _current_language
    path = get_settings_path()
    if path != _loaded_path:
        _loaded_path = path
        _current_language = _read_language_from_disk()
    return _current_language


def set_language(lang: str) -> str:
    """Persists ``lang`` and makes it the active language.

    Unsupported codes silently fall back to ``en_US``. Returns the language
    that is actually active after the call.
    """
    global _loaded_path, _current_language
    if lang not in _LANGUAGE_CODES:
        lang = DEFAULT_LANGUAGE

    settings = _read_settings()
    settings["language"] = lang
    _write_settings(settings)

    _loaded_path = get_settings_path()
    _current_language = lang
    return _current_language


def tr(key: str, **kwargs) -> str:
    """Translates ``key`` using the active language.

    Lookup order: active language -> en_US -> the raw key itself.
    If ``kwargs`` are supplied the result is formatted with ``str.format``.
    """
    lang = get_language()
    text = TRANSLATIONS.get(lang, {}).get(key)
    if text is None:
        text = TRANSLATIONS[DEFAULT_LANGUAGE].get(key)
    if text is None:
        text = key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


# ---------------------------------------------------------------------------
# Translation tables
# ---------------------------------------------------------------------------

_EN_US: Dict[str, str] = {
    # --- Common -------------------------------------------------------
    "common.cancel": "Cancel",
    "common.next": "Next",
    "common.save": "Save",
    # --- Shared protocol / mode labels --------------------------------
    "discovery.proto.compx_v1": "CompX / Beken",
    "discovery.proto.yjx_v1": "YJX-Chip 2.4G",
    "discovery.proto.gamesir_v1": "GameSir XInput",
    "discovery.proto.nordic_v1": "Nordic 4K/8K RF",
    "discovery.proto.hidpp_v2": "Logitech Lightspeed",
    "discovery.proto.razer_v1": "Razer HyperSpeed",
    "discovery.proto.steelseries_v1": "SteelSeries Wireless",
    "discovery.proto.corsair_v1": "Corsair Slipstream",
    "discovery.proto.hyperx_v1": "HyperX Wireless",
    "discovery.proto.actions_v1": "Wireless Headset",
    "discovery.proto.generic_hid": "Standard HID Battery",
    # --- Menu ---------------------------------------------------------
    "menu.language": "Language",
    # --- Popup / dashboard --------------------------------------------
    "popup.tooltip.find": "Find & configure new devices",
    "popup.tooltip.refresh": "Refresh battery now",
    "popup.tooltip.menu": "Options & Settings",
    "popup.tooltip.close": "Close",
    "popup.footer.initial": "Click ⚙ for app settings | ••• on cards for device options",
    "popup.footer.refreshing": "Refreshing telemetry...",
    "popup.footer.options": "Right-click tray icon or click ⚙ for options",
    "popup.empty.title": "No supported wireless peripheral detected.",
    "popup.empty.find": "Find New Devices",
    "popup.card.bt_required": "BT Req.",
    "popup.card.wired_badge": "🔌 Wired",
    "popup.card.off": "OFF",
    "popup.card.charging_suffix": " ⚡",
    "popup.card.options_tooltip": "Options for {name}",
    "popup.card.state.bluetooth": "Connect via Bluetooth to monitor",
    "popup.card.state.wired": "Wired device • Continuous power",
    "popup.card.state.disconnected": "Disconnected / Deep Sleep",
    "popup.card.state.fully_charged": "⚡ Fully Charged",
    "popup.card.state.charging_eta": "⚡ Charging • {eta}",
    "popup.card.state.charging": "⚡ Charging via cable/dock",
    "popup.card.state.critical": "Critical Battery — Charge now!",
    "popup.card.state.low": "Low Battery",
    "popup.card.state.active": "Active • Discharging",
    "popup.card.action.change_protocol": "🔁 Change Protocol...",
    "popup.card.action.rename": "✏️ Rename Device...",
    "popup.card.action.change_type": "🏷️ Change Type / Icon...",
    "popup.card.action.remove": "🗑️ Remove Device...",
    "popup.proto.compx_v1": "2.4G / USB",
    "popup.proto.yjx_v1": "YJX 2.4G",
    "popup.proto.gamesir_v1": "GameSir 2.4G",
    "popup.proto.nordic_v1": "4K/8K RF",
    "popup.proto.hidpp_v2": "Lightspeed",
    "popup.proto.razer_v1": "HyperSpeed",
    "popup.proto.steelseries_v1": "SteelSeries",
    "popup.proto.corsair_v1": "Slipstream",
    "popup.proto.hyperx_v1": "HyperX",
    "popup.proto.sysfs_power_supply": "System / BT",
    "popup.proto.bluetooth": "Bluetooth",
    "popup.proto.actions_v1": "2.4G Dongle",
    "popup.proto.generic_hid": "Standard HID",
    "popup.proto.wired": "Wired USB",
    # --- Discovery dialog ---------------------------------------------
    "discovery.dialog.title": "Find & Configure Devices — AreYouLowBattery",
    "discovery.header.title": "Find & Configure Devices",
    "discovery.header.subtitle": "Scan USB ports to configure new wireless peripherals",
    "discovery.btn.rescan": "↻ Rescan",
    "discovery.btn.done": "Done",
    "discovery.card.unknown_name": "Wireless Peripheral (0x{vendor:04x}:0x{product:04x})",
    "discovery.field.name": "Name:",
    "discovery.field.category": "Category:",
    "discovery.field.protocol": "Protocol:",
    "discovery.category.other": "Other",
    "discovery.category.mouse": "Mouse",
    "discovery.category.keyboard": "Keyboard",
    "discovery.category.headset": "Headset",
    "discovery.category.gamepad": "Gamepad",
    "discovery.mode.requires_bluetooth": "2.4G Dongle (Requires Bluetooth for battery)",
    "discovery.mode.compx_v1": "2.4G CompX / Beken (Ajazz, Delux, Pulsar, Keychron)",
    "discovery.mode.yjx_v1": "2.4G YJX-Chip (Smailwolf RS7, EWEADN G5, MCHOSE G7)",
    "discovery.mode.gamesir_v1": "2.4G GameSir XInput (Cyclone 2)",
    "discovery.mode.nordic_v1": "2.4G Nordic 4K/8K RF (VXE, ATK, Scyrox, Lamzu)",
    "discovery.mode.hidpp_v2": "2.4G Logitech Lightspeed & Bolt (G Pro, G502, G915)",
    "discovery.mode.hidpp_v1": "2.4G Logitech HID++ 1.0 (Legacy Nano Receiver M185/M220)",
    "discovery.mode.razer_v1": "2.4G Razer HyperSpeed (Viper, DeathAdder, Basilisk)",
    "discovery.mode.steelseries_v1": "2.4G SteelSeries (Aerox, Rival, Arctis, Nova)",
    "discovery.mode.corsair_v1": "2.4G Corsair Slipstream (Dark Core, Virtuoso, HS80)",
    "discovery.mode.hyperx_v1": "2.4G HyperX Wireless (Cloud Flight/II/Alpha, Pulsefire)",
    "discovery.mode.actions_v1": "2.4G Wireless Headset (Actions Semi / Baseus)",
    "discovery.mode.generic_hid": "2.4G Standard USB HID Battery (Generic 0x85)",
    "discovery.mode.is_wired": "Wired USB (Continuous power, no battery alerts)",
    "discovery.btn.test": "Test Protocol",
    "discovery.btn.save": "Save Device Profile",
    "discovery.btn.restore": "Restore Device",
    "discovery.btn.testing": "Testing...",
    "discovery.btn.restored": "✓ Device Restored",
    "discovery.btn.saved": "✓ Profile Saved",
    "discovery.status.ignored": "ℹ️ Device was previously removed/hidden. Click 'Restore Device' to unhide it.",
    "discovery.status.probing": "Probing 2.4G telemetry channels (CompX, Nordic, Logitech, Razer, SteelSeries, Corsair, HyperX)...",
    "discovery.status.detected": "✓ Detected via {proto}! Battery: {pct}%",
    "discovery.status.xpad": "Dongle uses standard Xbox/xpad protocol (no 2.4G battery channel). Keep 'Requires Bluetooth'.",
    "discovery.status.no_response": "No response from 2.4G protocols. If your peripheral also supports Bluetooth, select 'Requires Bluetooth'.",
    "discovery.status.restored": "Active! Device restored to dashboard.",
    "discovery.status.saved": "Active! Profile saved to user directory.",
    "discovery.msg.invalid_name.title": "Invalid Name",
    "discovery.msg.invalid_name.body": "Please enter a valid peripheral name.",
    "discovery.msg.save_error.title": "Error Saving Profile",
    "discovery.msg.save_error.body": "Could not write profile YAML:\n{e}",
    "discovery.udev.title": "2.4G Device Permissions (udev)",
    "discovery.udev.title_active": "✓ 2.4G Device Permissions Active",
    "discovery.udev.desc": "Install udev rules to access 2.4G mice & keyboards without root.",
    "discovery.udev.desc_active": "Hardened rules active. Click 'Update' if a newly connected device needs access.",
    "discovery.udev.desc_updated": "Hardened rules active. Permissions updated.",
    "discovery.udev.btn_install": "Install Rules",
    "discovery.udev.btn_update": "Update",
    "discovery.empty.scan": (
        "✓ All connected wireless peripherals are already configured!\n\n"
        "To configure a new device, plug its 2.4G dongle into USB and click Rescan."
    ),
    # --- Tray ---------------------------------------------------------
    "tray.tooltip.reading": "AreYouLowBattery - Reading peripherals...",
    "tray.tooltip.no_device": "AreYouLowBattery: No supported device active",
    "tray.status.reading": "Reading battery...",
    "tray.status.no_device": "No active device",
    "tray.menu.find": "Find devices...",
    "tray.menu.rename": "Rename device...",
    "tray.menu.change_type": "Change device type...",
    "tray.menu.change_protocol": "Change device protocol...",
    "tray.menu.remove": "Remove device...",
    "tray.menu.refresh": "Refresh now",
    "tray.menu.game_mode_active": "Game Mode active",
    "tray.menu.pause_polling": "Pause Polling (Game Mode)",
    "tray.menu.autostart": "Start with system",
    "tray.menu.diagnostics": "Export diagnostic log...",
    "tray.menu.updates": "Check for updates...",
    "tray.menu.uninstall": "Uninstall...",
    "tray.menu.quit": "Quit",
    "tray.menu.udev": "Configure udev permissions (2.4G)...",
    "tray.line.bluetooth": "{icon}  {name}: 2.4G (Connect via Bluetooth to monitor)",
    "tray.line.wired": "{icon}  {name}: Wired USB (Continuous power)",
    "tray.line.disconnected": "{icon}  {name}: Disconnected (OFF)",
    "tray.line.charging_unknown": "{icon}  {name}: Charging via cable{eta}",
    "tray.line.charging": "{icon}  {name}: {pct}% Charging{eta}",
    "tray.line.percentage": "{icon}  {name}: {pct}%",
    "tray.notify.critical.title": "{name} — Critical Battery ({pct}%)",
    "tray.notify.critical.body": "Battery is critically low. Connect the charger to avoid sudden power off.",
    "tray.notify.low.title": "{name} — Low Battery ({pct}%)",
    "tray.notify.low.body": "Battery level is low. Consider charging soon.",
    "tray.notify.tray_started": "Battery monitor is running in your System Tray (check the ^ arrow).",
    "tray.dialog.rename.title": "Rename Device",
    "tray.dialog.rename.select_prompt": "Select device to rename:",
    "tray.dialog.rename.new_name": "New name for '{name}':",
    "tray.dialog.select_device.title": "Select Device",
    "tray.dialog.select_device.change_type": "Select device to change type:",
    "tray.dialog.change_type.title": "Change Device Type / Icon",
    "tray.dialog.change_type.prompt": "Select category for <b>{name}</b>:",
    "tray.dialog.change_protocol.title": "Change Protocol",
    "tray.dialog.change_protocol.select_device": "Select device:",
    "tray.dialog.change_protocol.prompt": "Select new protocol for '{name}':",
    "tray.dialog.remove.title": "Remove Device",
    "tray.dialog.remove.select_device": "Select device to remove:",
    "tray.dialog.remove.confirm": (
        "Are you sure you want to remove '{name}' from the battery monitor?\n\n"
        "This will hide the device and delete any custom profile created for it."
    ),
    "tray.dialog.uninstall.title": "Uninstall AreYouLowBattery",
    "tray.dialog.uninstall.confirm": (
        "Are you sure you want to completely uninstall AreYouLowBattery?\n\n"
        "This will stop and remove the background service, delete the binary and "
        "clean up all configuration files."
    ),
    "tray.dialog.diag.title": "Diagnostic Log Exported",
    "tray.dialog.diag.body": "Diagnostic report saved to:\n\n{path}\n\nYou can send this file to help troubleshoot your device.",
    "tray.dialog.diag_error.title": "Diagnostic Error",
    "tray.dialog.diag_error.body": "Could not generate diagnostic report:\n{e}",
    # --- udev installer ----------------------------------------------
    "udev.error.title": "Error",
    "udev.error.rules_missing": "Could not locate 99-areyoulowbattery.rules file.\n\nPlease reinstall AreYouLowBattery.",
    "udev.pkexec_missing.title": "pkexec Not Found",
    "udev.pkexec_missing.body": (
        "polkit 'pkexec' utility was not found on your system.\n\n"
        "Please manually install the rules in terminal:\n\n"
        "sudo cp '{rules_src}' {target}\n"
        "sudo udevadm control --reload && sudo udevadm trigger"
    ),
    "udev.success.title": "Permissions Configured",
    "udev.success.body": (
        "✓ udev rules installed successfully!\n\n"
        "Your 2.4G wireless peripherals are now accessible without root."
    ),
    "udev.auth_failed.title": "Authorization Failed",
    "udev.auth_failed.body": (
        "Administrator authorization was denied or unavailable.\n\n"
        "Try again and enter your password, or install manually in a terminal:\n\n"
        "sudo cp '{rules_src}' {target}\n"
        "sudo udevadm control --reload && sudo udevadm trigger"
    ),
    "udev.install_failed.title": "Installation Failed",
    "udev.install_failed.body": "Could not install udev rules:\n\n{error}",
    "udev.exec_failed.body": "Failed to execute pkexec:\n{e}",
    # --- Updater ------------------------------------------------------
    "updater.dialog.title": "Update Available - AreYouLowBattery",
    "updater.dialog.heading": "<b>A new version is available!</b>",
    "updater.dialog.version": "Current: <b>v{current}</b>  →  Latest: <b>{latest}</b>",
    "updater.dialog.notes_label": "What's New:",
    "updater.dialog.no_notes": "No release notes provided for this version.",
    "updater.btn.view_github": "View on GitHub",
    "updater.btn.remind_later": "Remind Me Later",
    "updater.btn.update_now": "Update Now",
    "updater.btn.download_install": "Download & Install",
    "updater.btn.cancel": "Cancel",
    "updater.btn.close": "Close",
    "updater.blocked.title": "Update Blocked",
    "updater.blocked.body": (
        "This release does not publish a SHA-256 checksum for its installer, "
        "so automatic installation was blocked for your safety.\n\n"
        "The release page will open so you can download it manually."
    ),
    "updater.status.connecting": "Connecting to GitHub...",
    "updater.status.downloading_pct": "Downloading update: {down:.1f} MB / {total:.1f} MB ({pct}%)",
    "updater.status.downloading": "Downloading update: {down:.1f} MB...",
    "updater.status.complete": "Download complete! Launching update...",
    "updater.status.failed": "Download failed.",
    "updater.error.title": "Update Error",
    "updater.error.run_installer": "Failed to run installer:\n{e}",
    "updater.installed.title": "Update Installed",
    "updater.installed.body": "AreYouLowBattery has been updated to {tag} and restarted successfully!",
    "updater.downloaded.title": "Download Complete",
    "updater.downloaded.body": "Binary downloaded to:\n{path}\n\nYou can replace your installation with this binary.",
    "updater.download_error.title": "Download Error",
    "updater.download_error.body": "Failed to download update:\n{error}\n\nYou can download it manually from the release page.",
    "updater.check_failed.title": "Update Check Failed",
    "updater.check_failed.body": "Unable to connect to GitHub to check for updates:\n{error}\n\nPlease check your internet connection.",
    "updater.up_to_date.title": "Up to Date",
    "updater.up_to_date.body": "You are running the latest version of AreYouLowBattery (v{version}).",
}


_PT_BR: Dict[str, str] = {
    # --- Common -------------------------------------------------------
    "common.cancel": "Cancelar",
    "common.next": "Próximo",
    "common.save": "Salvar",
    # --- Shared protocol / mode labels --------------------------------
    "discovery.proto.compx_v1": "CompX / Beken",
    "discovery.proto.yjx_v1": "YJX-Chip 2.4G",
    "discovery.proto.gamesir_v1": "GameSir XInput",
    "discovery.proto.nordic_v1": "Nordic 4K/8K RF",
    "discovery.proto.hidpp_v2": "Logitech Lightspeed",
    "discovery.proto.razer_v1": "Razer HyperSpeed",
    "discovery.proto.steelseries_v1": "SteelSeries Sem Fio",
    "discovery.proto.corsair_v1": "Corsair Slipstream",
    "discovery.proto.hyperx_v1": "HyperX Sem Fio",
    "discovery.proto.actions_v1": "Headset Sem Fio",
    "discovery.proto.generic_hid": "Bateria HID Padrão",
    # --- Menu ---------------------------------------------------------
    "menu.language": "Idioma",
    # --- Popup / dashboard --------------------------------------------
    "popup.tooltip.find": "Localizar e configurar novos dispositivos",
    "popup.tooltip.refresh": "Atualizar bateria agora",
    "popup.tooltip.menu": "Opções e configurações",
    "popup.tooltip.close": "Fechar",
    "popup.footer.initial": "Clique em ⚙ para configurações | ••• nos cartões para opções do dispositivo",
    "popup.footer.refreshing": "Atualizando telemetria...",
    "popup.footer.options": "Clique com o botão direito no ícone da bandeja ou em ⚙ para opções",
    "popup.empty.title": "Nenhum periférico sem fio compatível detectado.",
    "popup.empty.find": "Buscar novos dispositivos",
    "popup.card.bt_required": "BT Req.",
    "popup.card.wired_badge": "🔌 Com fio",
    "popup.card.off": "OFF",
    "popup.card.charging_suffix": " ⚡",
    "popup.card.options_tooltip": "Opções para {name}",
    "popup.card.state.bluetooth": "Conecte via Bluetooth para monitorar",
    "popup.card.state.wired": "Dispositivo com fio • Energia contínua",
    "popup.card.state.disconnected": "Desconectado / Suspensão profunda",
    "popup.card.state.fully_charged": "⚡ Totalmente carregado",
    "popup.card.state.charging_eta": "⚡ Carregando • {eta}",
    "popup.card.state.charging": "⚡ Carregando via cabo/dock",
    "popup.card.state.critical": "Bateria crítica — Carregue agora!",
    "popup.card.state.low": "Bateria baixa",
    "popup.card.state.active": "Ativo • Descarregando",
    "popup.card.action.change_protocol": "🔁 Alterar protocolo...",
    "popup.card.action.rename": "✏️ Renomear dispositivo...",
    "popup.card.action.change_type": "🏷️ Alterar tipo / ícone...",
    "popup.card.action.remove": "🗑️ Remover dispositivo...",
    "popup.proto.compx_v1": "2.4G / USB",
    "popup.proto.yjx_v1": "YJX 2.4G",
    "popup.proto.gamesir_v1": "GameSir 2.4G",
    "popup.proto.nordic_v1": "4K/8K RF",
    "popup.proto.hidpp_v2": "Lightspeed",
    "popup.proto.razer_v1": "HyperSpeed",
    "popup.proto.steelseries_v1": "SteelSeries",
    "popup.proto.corsair_v1": "Slipstream",
    "popup.proto.hyperx_v1": "HyperX",
    "popup.proto.sysfs_power_supply": "Sistema / BT",
    "popup.proto.bluetooth": "Bluetooth",
    "popup.proto.actions_v1": "Dongle 2.4G",
    "popup.proto.generic_hid": "HID Padrão",
    "popup.proto.wired": "USB com fio",
    # --- Discovery dialog ---------------------------------------------
    "discovery.dialog.title": "Localizar e configurar dispositivos — AreYouLowBattery",
    "discovery.header.title": "Localizar e configurar dispositivos",
    "discovery.header.subtitle": "Escaneie as portas USB para configurar novos periféricos sem fio",
    "discovery.btn.rescan": "↻ Escanear novamente",
    "discovery.btn.done": "Concluído",
    "discovery.card.unknown_name": "Periférico sem fio (0x{vendor:04x}:0x{product:04x})",
    "discovery.field.name": "Nome:",
    "discovery.field.category": "Categoria:",
    "discovery.field.protocol": "Protocolo:",
    "discovery.category.other": "Outro",
    "discovery.category.mouse": "Mouse",
    "discovery.category.keyboard": "Teclado",
    "discovery.category.headset": "Headset",
    "discovery.category.gamepad": "Controle",
    "discovery.mode.requires_bluetooth": "Dongle 2.4G (requer Bluetooth para a bateria)",
    "discovery.mode.compx_v1": "2.4G CompX / Beken (Ajazz, Delux, Pulsar, Keychron)",
    "discovery.mode.yjx_v1": "2.4G YJX-Chip (Smailwolf RS7, EWEADN G5, MCHOSE G7)",
    "discovery.mode.gamesir_v1": "2.4G GameSir XInput (Cyclone 2)",
    "discovery.mode.nordic_v1": "2.4G Nordic 4K/8K RF (VXE, ATK, Scyrox, Lamzu)",
    "discovery.mode.hidpp_v2": "2.4G Logitech Lightspeed e Bolt (G Pro, G502, G915)",
    "discovery.mode.hidpp_v1": "2.4G Logitech HID++ 1.0 (receptor Nano legado M185/M220)",
    "discovery.mode.razer_v1": "2.4G Razer HyperSpeed (Viper, DeathAdder, Basilisk)",
    "discovery.mode.steelseries_v1": "2.4G SteelSeries (Aerox, Rival, Arctis, Nova)",
    "discovery.mode.corsair_v1": "2.4G Corsair Slipstream (Dark Core, Virtuoso, HS80)",
    "discovery.mode.hyperx_v1": "2.4G HyperX Wireless (Cloud Flight/II/Alpha, Pulsefire)",
    "discovery.mode.actions_v1": "Headset sem fio 2.4G (Actions Semi / Baseus)",
    "discovery.mode.generic_hid": "Bateria HID USB padrão 2.4G (genérico 0x85)",
    "discovery.mode.is_wired": "USB com fio (energia contínua, sem alertas de bateria)",
    "discovery.btn.test": "Testar protocolo",
    "discovery.btn.save": "Salvar perfil do dispositivo",
    "discovery.btn.restore": "Restaurar dispositivo",
    "discovery.btn.testing": "Testando...",
    "discovery.btn.restored": "✓ Dispositivo restaurado",
    "discovery.btn.saved": "✓ Perfil salvo",
    "discovery.status.ignored": "ℹ️ O dispositivo foi removido/ocultado anteriormente. Clique em 'Restaurar dispositivo' para exibi-lo novamente.",
    "discovery.status.probing": "Sondando canais de telemetria 2.4G (CompX, Nordic, Logitech, Razer, SteelSeries, Corsair, HyperX)...",
    "discovery.status.detected": "✓ Detectado via {proto}! Bateria: {pct}%",
    "discovery.status.xpad": "O dongle usa o protocolo padrão Xbox/xpad (sem canal de bateria 2.4G). Mantenha 'Requer Bluetooth'.",
    "discovery.status.no_response": "Sem resposta dos protocolos 2.4G. Se o seu periférico também suporta Bluetooth, selecione 'Requer Bluetooth'.",
    "discovery.status.restored": "Ativo! Dispositivo restaurado no painel.",
    "discovery.status.saved": "Ativo! Perfil salvo no diretório do usuário.",
    "discovery.msg.invalid_name.title": "Nome inválido",
    "discovery.msg.invalid_name.body": "Digite um nome de periférico válido.",
    "discovery.msg.save_error.title": "Erro ao salvar perfil",
    "discovery.msg.save_error.body": "Não foi possível gravar o perfil YAML:\n{e}",
    "discovery.udev.title": "Permissões de dispositivos 2.4G (udev)",
    "discovery.udev.title_active": "✓ Permissões de dispositivos 2.4G ativas",
    "discovery.udev.desc": "Instale as regras udev para acessar mouses e teclados 2.4G sem root.",
    "discovery.udev.desc_active": "Regras reforçadas ativas. Clique em 'Atualizar' se um dispositivo recém-conectado precisar de acesso.",
    "discovery.udev.desc_updated": "Regras reforçadas ativas. Permissões atualizadas.",
    "discovery.udev.btn_install": "Instalar regras",
    "discovery.udev.btn_update": "Atualizar",
    "discovery.empty.scan": (
        "✓ Todos os periféricos sem fio conectados já estão configurados!\n\n"
        "Para configurar um novo dispositivo, conecte o dongle 2.4G na USB e clique em Escanear novamente."
    ),
    # --- Tray ---------------------------------------------------------
    "tray.tooltip.reading": "AreYouLowBattery - Lendo periféricos...",
    "tray.tooltip.no_device": "AreYouLowBattery: Nenhum dispositivo compatível ativo",
    "tray.status.reading": "Lendo bateria...",
    "tray.status.no_device": "Nenhum dispositivo ativo",
    "tray.menu.find": "Localizar dispositivos...",
    "tray.menu.rename": "Renomear dispositivo...",
    "tray.menu.change_type": "Alterar tipo do dispositivo...",
    "tray.menu.change_protocol": "Alterar protocolo do dispositivo...",
    "tray.menu.remove": "Remover dispositivo...",
    "tray.menu.refresh": "Atualizar agora",
    "tray.menu.game_mode_active": "Modo Jogo ativo",
    "tray.menu.pause_polling": "Pausar monitoramento (Modo Jogo)",
    "tray.menu.autostart": "Iniciar com o sistema",
    "tray.menu.diagnostics": "Exportar log de diagnóstico...",
    "tray.menu.updates": "Verificar atualizações...",
    "tray.menu.uninstall": "Desinstalar...",
    "tray.menu.quit": "Sair",
    "tray.menu.udev": "Configurar permissões udev (2.4G)...",
    "tray.line.bluetooth": "{icon}  {name}: 2.4G (Conecte via Bluetooth para monitorar)",
    "tray.line.wired": "{icon}  {name}: USB com fio (energia contínua)",
    "tray.line.disconnected": "{icon}  {name}: Desconectado (OFF)",
    "tray.line.charging_unknown": "{icon}  {name}: Carregando via cabo{eta}",
    "tray.line.charging": "{icon}  {name}: {pct}% carregando{eta}",
    "tray.line.percentage": "{icon}  {name}: {pct}%",
    "tray.notify.critical.title": "{name} — Bateria crítica ({pct}%)",
    "tray.notify.critical.body": "A bateria está criticamente baixa. Conecte o carregador para evitar desligamento repentino.",
    "tray.notify.low.title": "{name} — Bateria baixa ({pct}%)",
    "tray.notify.low.body": "O nível da bateria está baixo. Considere carregar em breve.",
    "tray.notify.tray_started": "O monitor de bateria está em execução na bandeja do sistema (veja a seta ^).",
    "tray.dialog.rename.title": "Renomear dispositivo",
    "tray.dialog.rename.select_prompt": "Selecione o dispositivo a renomear:",
    "tray.dialog.rename.new_name": "Novo nome para '{name}':",
    "tray.dialog.select_device.title": "Selecionar dispositivo",
    "tray.dialog.select_device.change_type": "Selecione o dispositivo para alterar o tipo:",
    "tray.dialog.change_type.title": "Alterar tipo / ícone do dispositivo",
    "tray.dialog.change_type.prompt": "Selecione a categoria para <b>{name}</b>:",
    "tray.dialog.change_protocol.title": "Alterar protocolo",
    "tray.dialog.change_protocol.select_device": "Selecione o dispositivo:",
    "tray.dialog.change_protocol.prompt": "Selecione o novo protocolo para '{name}':",
    "tray.dialog.remove.title": "Remover dispositivo",
    "tray.dialog.remove.select_device": "Selecione o dispositivo a remover:",
    "tray.dialog.remove.confirm": (
        "Tem certeza de que deseja remover '{name}' do monitor de bateria?\n\n"
        "Isso ocultará o dispositivo e excluirá qualquer perfil personalizado criado para ele."
    ),
    "tray.dialog.uninstall.title": "Desinstalar o AreYouLowBattery",
    "tray.dialog.uninstall.confirm": (
        "Tem certeza de que deseja desinstalar completamente o AreYouLowBattery?\n\n"
        "Isso interromperá e removerá o serviço em segundo plano, excluirá o binário "
        "e limpará todos os arquivos de configuração."
    ),
    "tray.dialog.diag.title": "Log de diagnóstico exportado",
    "tray.dialog.diag.body": "Relatório de diagnóstico salvo em:\n\n{path}\n\nVocê pode enviar este arquivo para ajudar a diagnosticar seu dispositivo.",
    "tray.dialog.diag_error.title": "Erro de diagnóstico",
    "tray.dialog.diag_error.body": "Não foi possível gerar o relatório de diagnóstico:\n{e}",
    # --- udev installer ----------------------------------------------
    "udev.error.title": "Erro",
    "udev.error.rules_missing": "Não foi possível localizar o arquivo 99-areyoulowbattery.rules.\n\nReinstale o AreYouLowBattery.",
    "udev.pkexec_missing.title": "pkexec não encontrado",
    "udev.pkexec_missing.body": (
        "O utilitário polkit 'pkexec' não foi encontrado no seu sistema.\n\n"
        "Instale as regras manualmente no terminal:\n\n"
        "sudo cp '{rules_src}' {target}\n"
        "sudo udevadm control --reload && sudo udevadm trigger"
    ),
    "udev.success.title": "Permissões configuradas",
    "udev.success.body": (
        "✓ Regras udev instaladas com sucesso!\n\n"
        "Seus periféricos sem fio 2.4G agora estão acessíveis sem root."
    ),
    "udev.auth_failed.title": "Falha na autorização",
    "udev.auth_failed.body": (
        "A autorização de administrador foi negada ou não está disponível.\n\n"
        "Tente novamente e digite sua senha, ou instale manualmente no terminal:\n\n"
        "sudo cp '{rules_src}' {target}\n"
        "sudo udevadm control --reload && sudo udevadm trigger"
    ),
    "udev.install_failed.title": "Falha na instalação",
    "udev.install_failed.body": "Não foi possível instalar as regras udev:\n\n{error}",
    "udev.exec_failed.body": "Falha ao executar pkexec:\n{e}",
    # --- Updater ------------------------------------------------------
    "updater.dialog.title": "Atualização disponível - AreYouLowBattery",
    "updater.dialog.heading": "<b>Uma nova versão está disponível!</b>",
    "updater.dialog.version": "Atual: <b>v{current}</b>  →  Mais recente: <b>{latest}</b>",
    "updater.dialog.notes_label": "Novidades:",
    "updater.dialog.no_notes": "Nenhuma nota de lançamento informada para esta versão.",
    "updater.btn.view_github": "Ver no GitHub",
    "updater.btn.remind_later": "Lembrar depois",
    "updater.btn.update_now": "Atualizar agora",
    "updater.btn.download_install": "Baixar e instalar",
    "updater.btn.cancel": "Cancelar",
    "updater.btn.close": "Fechar",
    "updater.blocked.title": "Atualização bloqueada",
    "updater.blocked.body": (
        "Este lançamento não publica um checksum SHA-256 para o instalador, "
        "então a instalação automática foi bloqueada por segurança.\n\n"
        "A página de lançamento será aberta para você baixar manualmente."
    ),
    "updater.status.connecting": "Conectando ao GitHub...",
    "updater.status.downloading_pct": "Baixando atualização: {down:.1f} MB / {total:.1f} MB ({pct}%)",
    "updater.status.downloading": "Baixando atualização: {down:.1f} MB...",
    "updater.status.complete": "Download concluído! Iniciando atualização...",
    "updater.status.failed": "Falha no download.",
    "updater.error.title": "Erro na atualização",
    "updater.error.run_installer": "Falha ao executar o instalador:\n{e}",
    "updater.installed.title": "Atualização instalada",
    "updater.installed.body": "O AreYouLowBattery foi atualizado para {tag} e reiniciado com sucesso!",
    "updater.downloaded.title": "Download concluído",
    "updater.downloaded.body": "Binário baixado em:\n{path}\n\nVocê pode substituir sua instalação por este binário.",
    "updater.download_error.title": "Erro no download",
    "updater.download_error.body": "Não foi possível baixar a atualização:\n{error}\n\nVocê pode baixar manualmente na página de lançamento.",
    "updater.check_failed.title": "Falha ao verificar atualizações",
    "updater.check_failed.body": "Não foi possível conectar ao GitHub para verificar atualizações:\n{error}\n\nVerifique sua conexão com a internet.",
    "updater.up_to_date.title": "Atualizado",
    "updater.up_to_date.body": "Você já está usando a versão mais recente do AreYouLowBattery (v{version}).",
}


TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "en_US": _EN_US,
    "pt_BR": _PT_BR,
}
