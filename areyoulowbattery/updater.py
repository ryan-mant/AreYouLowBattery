import os
import sys
import re
import json
import ssl
import hashlib
import tempfile
import subprocess
import urllib.request
import urllib.error
from typing import Optional, Tuple, Dict, Any

try:
    from PySide6.QtCore import Qt, QThread, Signal, QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
        QProgressBar, QTextBrowser, QMessageBox, QApplication
    )
    HAS_QT = True
except (ImportError, OSError):
    HAS_QT = False
    Qt = None
    QThread = object
    QDialog = object
    Signal = lambda *args: None
    QUrl = None
    QDesktopServices = None
    QMessageBox = None
    QApplication = None

from areyoulowbattery import __version__
from areyoulowbattery.logger import logger

REPO_SLUG = "ryan-mant/AreYouLowBattery"
API_LATEST_URL = f"https://api.github.com/repos/{REPO_SLUG}/releases/latest"


def parse_version(v: str) -> Tuple[int, ...]:
    """
    Parses semantic version strings like 'v0.5.1', '0.5.0', 'v1.2.3-rc'
    into a tuple of integers (e.g. (0, 5, 1)).
    """
    cleaned = v.strip().lstrip("vV")
    parts = []
    for chunk in cleaned.split("."):
        digits = re.findall(r"\d+", chunk)
        if digits:
            parts.append(int(digits[0]))
        else:
            break
    return tuple(parts) if parts else (0, 0, 0)


def is_newer_version(candidate: str, current: str = __version__) -> bool:
    """Returns True if candidate version is strictly newer than current version."""
    return parse_version(candidate) > parse_version(current)


def _create_ssl_context() -> ssl.SSLContext:
    """
    Creates a secure SSLContext using system trust stores and certifi if available.
    Loads system Root certificates on Windows via ssl.enum_certificates("ROOT") and "CA".
    Strictly enforces valid certificate verification (never disables TLS).
    """
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass

    if sys.platform == "win32" and hasattr(ssl, "enum_certificates"):
        for store_name in ("ROOT", "CA"):
            try:
                for cert, encoding, trust in ssl.enum_certificates(store_name):
                    if encoding == "x509_asn":
                        try:
                            ctx.load_verify_locations(cdata=cert)
                        except Exception:
                            pass
            except Exception:
                pass
    return ctx


def extract_expected_sha256(release_info: Dict[str, Any], filename: str) -> Optional[str]:
    """
    Extracts the expected SHA-256 hash for the given asset.

    Source priority:
      1. GitHub API `assets[].digest` ("sha256:<hex>") computed by GitHub at upload time.
      2. Release notes, supporting formats:
           <sha256>  <filename>
           SHA256 (<filename>) = <sha256>
           SHA-256: <sha256>
    Returns None when no trusted hash is published (the updater then refuses to install).
    """
    for asset in release_info.get("assets", []) or []:
        if asset.get("name", "").lower() == filename.lower():
            digest = str(asset.get("digest") or "").strip().lower()
            if digest.startswith("sha256:") and re.fullmatch(r"[0-9a-f]{64}", digest[7:]):
                return digest[7:]

    body = release_info.get("body", "")
    if not body:
        return None

    fname_lower = filename.lower()
    for line in body.splitlines():
        line_clean = line.strip()
        if fname_lower in line_clean.lower():
            # Look for 64-character hex string
            m = re.search(r"\b([0-9a-fA-F]{64})\b", line_clean)
            if m:
                return m.group(1).lower()

    # Generic SHA-256 tag in release notes if only 1 asset is released
    assets = release_info.get("assets", [])
    if len(assets) == 1:
        m = re.search(r"sha[-_]?256\s*[:=]\s*([0-9a-fA-F]{64})", body, re.IGNORECASE)
        if m:
            return m.group(1).lower()

    return None


def fetch_latest_release(repo: str = REPO_SLUG, timeout: float = 6.0) -> Dict[str, Any]:
    """
    Fetches the latest release payload from GitHub Releases API with strict TLS verification.
    Raises urllib.error.URLError or json.JSONDecodeError on network/parsing failure.
    """
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/latest",
        headers={
            "User-Agent": f"AreYouLowBattery-Updater/{__version__}",
            "Accept": "application/vnd.github.v3+json",
        },
    )
    ssl_ctx = _create_ssl_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx) as resp:
        if resp.status != 200:
            raise urllib.error.HTTPError(
                resp.url, resp.status, f"HTTP error {resp.status}", resp.headers, None
            )
        data = json.loads(resp.read().decode("utf-8"))
        return data


def find_matching_asset(release_info: Dict[str, Any], platform: str = sys.platform) -> Optional[Dict[str, Any]]:
    """
    Selects the most suitable release binary asset for the current OS.
    - Windows: 'AreYouLowBattery-Windows-Setup.exe' (or any .exe installer)
    - Linux: 'areyoulowbattery-linux-x86_64' or 'areyoulowbattery'
    """
    assets = release_info.get("assets", [])
    if not assets:
        return None

    if platform == "win32":
        for a in assets:
            name = a.get("name", "").lower()
            if name == "areyoulowbattery-windows-setup.exe":
                return a
        for a in assets:
            if a.get("name", "").lower().endswith(".exe"):
                return a
    elif platform.startswith("linux"):
        for a in assets:
            name = a.get("name", "").lower()
            if "linux-x86_64" in name or name == "areyoulowbattery":
                return a

    return None


class DownloadWorker(QThread):
    progress = Signal(int, int)  # (bytes_downloaded, total_bytes)
    completed = Signal(str)      # local_file_path
    failed = Signal(str)         # error message

    def __init__(self, download_url: str, dest_filename: str, expected_sha256: Optional[str] = None):
        super().__init__()
        self.download_url = download_url
        self.dest_filename = dest_filename
        self.expected_sha256 = expected_sha256
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            req = urllib.request.Request(
                self.download_url,
                headers={"User-Agent": f"AreYouLowBattery-Updater/{__version__}"},
            )
            if not self.expected_sha256:
                self.failed.emit(
                    "Security Check Failed: this release does not publish a SHA-256 checksum, "
                    "so the download was refused. Please download it manually from the release page."
                )
                return

            # Private (0700) per-download directory + sanitized filename:
            # prevents local file collision/symlink tricks and path traversal via release metadata.
            safe_name = os.path.basename(self.dest_filename.replace("\\", "/")) or "update_installer"
            dest_dir = tempfile.mkdtemp(prefix="areyoulowbattery-update-")
            target_path = os.path.join(dest_dir, safe_name)

            ssl_ctx = _create_ssl_context()
            hasher = hashlib.sha256()

            with urllib.request.urlopen(req, timeout=30.0, context=ssl_ctx) as resp:
                total_size = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 64 * 1024  # 64 KB chunks

                with open(target_path, "wb") as out_file:
                    while True:
                        if self._is_cancelled:
                            try:
                                os.remove(target_path)
                                os.rmdir(dest_dir)
                            except OSError:
                                pass
                            return

                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        hasher.update(chunk)
                        downloaded += len(chunk)
                        self.progress.emit(downloaded, total_size)

            computed_sha256 = hasher.hexdigest().lower()
            logger.info("Download completed (%s bytes). SHA-256: %s", downloaded, computed_sha256)

            clean_expected = self.expected_sha256.lower().strip()
            if computed_sha256 != clean_expected:
                try:
                    os.remove(target_path)
                    os.rmdir(dest_dir)
                except OSError:
                    pass
                self.failed.emit(
                    f"Security Check Failed: SHA-256 hash mismatch!\nExpected: {clean_expected}\nGot: {computed_sha256}"
                )
                return

            self.completed.emit(target_path)
        except Exception as e:
            self.failed.emit(str(e))


class UpdateDialog(QDialog):
    """
    Clean, dark-themed update dialog showing version diff, release notes,
    and automatic 1-click update installation.
    """

    def __init__(self, release_info: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.release_info = release_info
        self.tag_name = release_info.get("tag_name", "v0.0.0")
        self.html_url = release_info.get("html_url", f"https://github.com/{REPO_SLUG}/releases")
        self.asset = find_matching_asset(release_info)
        self.download_worker: Optional[DownloadWorker] = None

        self.setWindowTitle("Update Available - AreYouLowBattery")
        self.setFixedWidth(500)
        self.setStyleSheet("""
            QDialog {
                background-color: #0f172a;
                color: #f8fafc;
            }
            QLabel {
                color: #f8fafc;
            }
            QTextBrowser {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
                color: #cbd5e1;
                padding: 10px;
                font-size: 12px;
            }
            QPushButton {
                background-color: #1e293b;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 7px 16px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #334155;
            }
            QPushButton#primaryBtn {
                background-color: #0284c7;
                border: none;
                color: #ffffff;
            }
            QPushButton#primaryBtn:hover {
                background-color: #0369a1;
            }
            QPushButton#primaryBtn:disabled {
                background-color: #334155;
                color: #64748b;
            }
            QProgressBar {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                text-align: center;
                color: #ffffff;
                font-weight: 600;
                font-size: 11px;
                height: 18px;
            }
            QProgressBar::chunk {
                background-color: #38bdf8;
                border-radius: 5px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Header
        header_layout = QHBoxLayout()
        header_icon = QLabel("🎉")
        header_icon.setStyleSheet("font-size: 32px;")
        header_layout.addWidget(header_icon)

        title_layout = QVBoxLayout()
        title_lbl = QLabel(f"<b>A new version is available!</b>")
        title_lbl.setStyleSheet("font-size: 15px; color: #38bdf8;")
        version_lbl = QLabel(f"Current: <b>v{__version__}</b>  →  Latest: <b>{self.tag_name}</b>")
        version_lbl.setStyleSheet("font-size: 12px; color: #94a3b8;")
        title_layout.addWidget(title_lbl)
        title_layout.addWidget(version_lbl)
        header_layout.addLayout(title_layout, 1)

        layout.addLayout(header_layout)

        # Release Notes Label & View
        notes_label = QLabel("What's New:")
        notes_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #cbd5e1;")
        layout.addWidget(notes_label)

        self.notes_browser = QTextBrowser()
        body_text = self.release_info.get("body", "").strip() or "No release notes provided for this version."
        self.notes_browser.setPlainText(body_text)
        self.notes_browser.setFixedHeight(160)
        layout.addWidget(self.notes_browser)

        # Download Progress Area (hidden initially)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("font-size: 11px; color: #94a3b8;")
        self.status_lbl.setVisible(False)
        layout.addWidget(self.status_lbl)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.browser_btn = QPushButton("View on GitHub")
        self.browser_btn.clicked.connect(self._open_in_browser)
        btn_layout.addWidget(self.browser_btn)

        btn_layout.addStretch(1)

        self.close_btn = QPushButton("Remind Me Later")
        self.close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.close_btn)

        install_label = "Update Now"
        if sys.platform == "win32":
            install_label = "Download & Install"
        self.install_btn = QPushButton(install_label)
        self.install_btn.setObjectName("primaryBtn")
        self.install_btn.clicked.connect(self._start_update_action)
        btn_layout.addWidget(self.install_btn)

        layout.addLayout(btn_layout)

    def _open_in_browser(self):
        QDesktopServices.openUrl(QUrl(self.html_url))

    def _start_update_action(self):
        if not self.asset:
            # Fallback if no matching binary was attached
            QDesktopServices.openUrl(QUrl(self.html_url))
            self.accept()
            return

        download_url = self.asset.get("browser_download_url")
        if not download_url:
            QDesktopServices.openUrl(QUrl(self.html_url))
            self.accept()
            return

        asset_name = self.asset.get("name", "update_installer")
        expected_sha = extract_expected_sha256(self.release_info, asset_name)
        if not expected_sha:
            # Never download/execute a binary without a published checksum.
            QMessageBox.warning(
                self,
                "Update Blocked",
                "This release does not publish a SHA-256 checksum for its installer, "
                "so automatic installation was blocked for your safety.\n\n"
                "The release page will open so you can download it manually.",
            )
            QDesktopServices.openUrl(QUrl(self.html_url))
            self.accept()
            return

        self.install_btn.setEnabled(False)
        self.close_btn.setText("Cancel")
        self.progress_bar.setVisible(True)
        self.status_lbl.setVisible(True)
        self.status_lbl.setText(f"Connecting to GitHub...")

        self.download_worker = DownloadWorker(download_url, asset_name, expected_sha256=expected_sha)
        _ACTIVE_WORKERS.add(self.download_worker)
        self.download_worker.finished.connect(lambda: _ACTIVE_WORKERS.discard(self.download_worker))
        self.download_worker.progress.connect(self._on_download_progress)
        self.download_worker.completed.connect(self._on_download_completed)
        self.download_worker.failed.connect(self._on_download_failed)
        self.download_worker.start()

    def _on_download_progress(self, downloaded: int, total: int):
        if total > 0:
            pct = int((downloaded / total) * 100)
            self.progress_bar.setValue(pct)
            mb_down = downloaded / (1024 * 1024)
            mb_total = total / (1024 * 1024)
            self.status_lbl.setText(f"Downloading update: {mb_down:.1f} MB / {mb_total:.1f} MB ({pct}%)")
        else:
            mb_down = downloaded / (1024 * 1024)
            self.status_lbl.setText(f"Downloading update: {mb_down:.1f} MB...")

    def _on_download_completed(self, local_path: str):
        self.status_lbl.setText("Download complete! Launching update...")
        self.progress_bar.setValue(100)

        if sys.platform == "win32":
            # Launch Inno Setup installer
            try:
                subprocess.Popen([local_path])
                # Clean exit to release executable file locks for the installer
                QApplication.quit()
            except Exception as e:
                QMessageBox.critical(self, "Update Error", f"Failed to run installer:\n{e}")
                self.install_btn.setEnabled(True)
        else:
            # Linux: replace ~/.local/bin/areyoulowbattery or restart service
            target_bin = os.path.expanduser("~/.local/bin/areyoulowbattery")
            if os.path.exists(target_bin) or not getattr(sys, "frozen", False):
                try:
                    import shutil
                    os.chmod(local_path, 0o755)
                    os.makedirs(os.path.dirname(target_bin), exist_ok=True)
                    shutil.copy2(local_path, target_bin)
                    os.chmod(target_bin, 0o755)
                    # Restart systemd user service if running
                    subprocess.run(["systemctl", "--user", "restart", "areyoulowbattery.service"], check=False)
                    QMessageBox.information(
                        self,
                        "Update Installed",
                        f"AreYouLowBattery has been updated to {self.tag_name} and restarted successfully!",
                    )
                    QApplication.quit()
                    return
                except Exception as e:
                    logger.warning("Could not automatically replace binary: %s", e)

            # Fallback for manual replacement or source install
            QMessageBox.information(
                self,
                "Download Complete",
                f"Binary downloaded to:\n{local_path}\n\nYou can replace your installation with this binary.",
            )
            self.accept()

    def _on_download_failed(self, error_msg: str):
        self.status_lbl.setText("Download failed.")
        QMessageBox.warning(
            self,
            "Download Error",
            f"Failed to download update:\n{error_msg}\n\nYou can download it manually from the release page.",
        )
        self.install_btn.setEnabled(True)
        self.close_btn.setText("Close")

    def reject(self):
        if self.download_worker and self.download_worker.isRunning():
            self.download_worker.cancel()
            self.download_worker.wait(1000)
        super().reject()


_ACTIVE_WORKERS = set()


class CheckUpdateThread(QThread):
    finished_check = Signal(object, str)  # (release_dict_or_None, error_str_or_empty)

    def run(self):
        try:
            data = fetch_latest_release(REPO_SLUG)
            tag = data.get("tag_name", "")
            if is_newer_version(tag, __version__):
                self.finished_check.emit(data, "")
            else:
                self.finished_check.emit(None, "")
        except Exception as e:
            self.finished_check.emit(None, str(e))


def run_check_for_updates(parent=None, prompt_if_latest: bool = True):
    """
    Triggers a manual check for updates.
    Runs check asynchronously to keep the UI silky-smooth (0ms freeze).
    Prevents GC deallocation crashes and unintended app shutdown on Windows.
    """
    if not HAS_QT:
        logger.warning("Qt is not available in current environment; cannot display update dialog.")
        return None

    app = QApplication.instance()
    if app:
        app.setQuitOnLastWindowClosed(False)

    thread = CheckUpdateThread(parent)
    _ACTIVE_WORKERS.add(thread)

    def cleanup():
        _ACTIVE_WORKERS.discard(thread)

    thread.finished.connect(cleanup)

    def on_finished(release_info: Optional[Dict[str, Any]], error_msg: str):
        try:
            if error_msg:
                QMessageBox.warning(
                    parent,
                    "Update Check Failed",
                    f"Unable to connect to GitHub to check for updates:\n{error_msg}\n\nPlease check your internet connection.",
                )
            elif release_info:
                dlg = UpdateDialog(release_info, parent=parent)
                dlg.exec()
            else:
                if prompt_if_latest:
                    QMessageBox.information(
                        parent,
                        "Up to Date",
                        f"You are running the latest version of AreYouLowBattery (v{__version__}).",
                    )
        except Exception as e:
            logger.error("Failed to present update dialog/message: %s", e)

    thread.finished_check.connect(on_finished)
    thread.start()
    return thread
