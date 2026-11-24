"""Main window, modelled on the Windows 10 'Remote Desktop Connection' dialog."""
from __future__ import annotations

import os
import shlex
import subprocess
import time

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCursor, QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QCompleter, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QMenu, QMessageBox,
    QPlainTextEdit, QPushButton, QSizePolicy, QSpinBox, QStyle, QSystemTrayIcon, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import store
from ..freerdp import FreeRDPClient, build_args, detect_clients
from ..freerdp.monitors import detect_monitors
from ..freerdp.errors import Attempt, diagnose, timeout_diagnosis
from ..freerdp.certs import CertInfo, normalize_fingerprint, parse_certificate_prompt
from ..model import Drive, Floatbar, Profile
from ..runner import Runner

RESOLUTIONS = ["Fit to window / dynamic", "1280x720", "1366x768", "1600x900", "1920x1080",
               "2560x1440", "3840x2160", "Custom..."]
COLOR_DEPTHS = [("Server default", None), ("15 bit", 15), ("16 bit", 16),
                ("24 bit", 24), ("32 bit (best)", 32)]
SECURITY = [("Negotiate (default)", None), ("NLA", "nla"), ("TLS", "tls"),
            ("RDP", "rdp"), ("Extended NLA", "ext")]
CERT_MODES = [("Ask me at connect time", "ask"), ("Trust saved certificates only", "saved"),
              ("Trust any certificate (insecure)", "any")]
H264 = [("Off", None), ("AVC420", "AVC420"), ("AVC444 (best quality)", "AVC444")]
FLOATBAR_SHOW = [("Always", "always"), ("Fullscreen only", "fullscreen"), ("Window only", "window")]


TAB_ROW_CHROME = 36  # window margins and tab frame around the tab row
FORM_MIN_WIDTH = 400  # room for a fully qualified host name; no wider than needed
LOG_WIDTH = 520  # width of the log panel shown beside the form


from .theme import app_icon

DEFAULTS_LABEL = "(My defaults)"


class CredentialsDialog(QDialog):
    """Asks for the user name and password when Connect is pressed without them, like the
    Windows client. FreeRDP cannot ask itself: it has no terminal to prompt on."""

    def __init__(self, parent, target: str, username: str):
        super().__init__(parent)
        self.setWindowTitle("Enter your credentials")
        self.setMinimumWidth(360)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"Enter the credentials for {target}."))
        form = QFormLayout()
        self.user = QLineEdit(username)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        form.addRow("User name:", self.user)
        form.addRow("Password:", self.password)
        lay.addLayout(form)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        for edit in (self.user, self.password):
            edit.textChanged.connect(self._validate)
        self._validate()
        (self.password if username else self.user).setFocus()

    def _validate(self) -> None:
        ok = bool(self.user.text().strip() and self.password.text())
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(ok)

    def credentials(self) -> tuple[str, str]:
        return self.user.text().strip(), self.password.text()


class _TrayPanel(QWidget):
    """The tray menu's entries as a small window, for compositors that won't place a QMenu
    without a focused parent window (Wayland). Closes as soon as it loses focus."""

    def __init__(self, info: QAction, *actions: QAction):
        super().__init__(None, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("FreeRDC")
        lay = QVBoxLayout(self)
        self._info = QLabel()
        lay.addWidget(self._info)
        self._info_action = info
        for action in actions:
            btn = QPushButton(action.text())
            btn.clicked.connect(self.hide)
            btn.clicked.connect(action.trigger)
            lay.addWidget(btn)

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
            return
        self._info.setText(self._info_action.text())
        self.adjustSize()
        self.show()
        self.raise_()
        self.activateWindow()

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.ActivationChange and self.isVisible() and not self.isActiveWindow():
            self.hide()
        super().changeEvent(event)


class HostCombo(QComboBox):
    """Editable drop-down of recently used servers.

    Behaves like the QLineEdit it replaces (text / setText / textChanged), so the rest of
    the form doesn't care. Items carry the remembered {host, port, username} as item data."""

    clear_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setMaxVisibleItems(12)
        completer = self.completer()
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        self.textChanged = self.editTextChanged
        self.lineEdit().setContextMenuPolicy(Qt.CustomContextMenu)
        self.lineEdit().customContextMenuRequested.connect(self._context_menu)

    def keyPressEvent(self, event) -> None:
        # Down arrow in the text box opens the list of recent servers (Qt's default would
        # silently step through the entries without showing them).
        if (event.key() == Qt.Key_Down and event.modifiers() == Qt.NoModifier
                and self.count() > 0):
            self.showPopup()
            event.accept()
            return
        super().keyPressEvent(event)

    def text(self) -> str:
        return self.currentText()

    def setText(self, text: str) -> None:
        self.setEditText(text)

    def setPlaceholderText(self, text: str) -> None:
        self.lineEdit().setPlaceholderText(text)

    def set_recent(self, entries: list[dict]) -> None:
        typed = self.currentText()
        self.blockSignals(True)
        self.clear()
        for e in entries:
            self.addItem(store.server_label(e["host"], e["port"]), e)
        self.setEditText(typed)  # clear() wipes the edit box; keep what the user typed
        self.blockSignals(False)

    def _context_menu(self, pos) -> None:
        menu = self.lineEdit().createStandardContextMenu()
        menu.addSeparator()
        clear = menu.addAction("Clear recent servers")
        clear.setEnabled(self.count() > 0)
        clear.triggered.connect(self.clear_requested)
        menu.exec(self.lineEdit().mapToGlobal(pos))


def _combo(items) -> QComboBox:
    c = QComboBox()
    c.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    c.setMinimumContentsLength(14)
    for label, data in items:
        c.addItem(label, data)
    return c


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FreeRDC - Remote Desktop Connection")
        self.runner = Runner(self)
        self.runner.finished.connect(self._on_finished)
        self.runner.output.connect(self._on_output)
        self.runner.connected.connect(self._on_connected)
        self._session_up = False
        self._attempt: Attempt | None = None
        self._profile_fps: list[str] = []  # fingerprints that came with a loaded saved connection
        self._trust_timer = QTimer(self)   # refresh the trusted list shortly after the host changes
        self._trust_timer.setSingleShot(True)
        self._trust_timer.setInterval(150)
        self._trust_timer.timeout.connect(self._refresh_trusted)
        self._attempt_credentials: tuple[str, int, str, bool] | None = None
        self._attempt_server: tuple[str, int, str] | None = None
        self._t0 = 0.0
        self._timed_out = False
        self._tick = QTimer(self)  # refreshes "Connecting ... N s" once a second
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._update_elapsed)
        self._timeout_timer = QTimer(self)  # gives up on a server that never answers
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)
        self._backgrounded = False
        self._enter_pending = False
        self.tray: QSystemTrayIcon | None = None
        self.runner.certificate_prompt.connect(self._on_certificate_prompt)
        self._cert: CertInfo | None = None      # set while FreeRDP waits on a cert prompt
        self._last_output = ""
        self.clients: list[FreeRDPClient] = []

        outer = QHBoxLayout(self)
        left = self._form = QWidget()
        left.setMinimumWidth(FORM_MIN_WIDTH)
        root = QVBoxLayout(left)
        root.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(left, 0)
        title = QLabel("<span style='font-size:20pt;'>Remote Desktop</span><br>"
                       "<span style='font-size:16pt;'><b>Connection</b></span>")
        root.addWidget(title)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._general_tab(), "General")
        self.tabs.addTab(self._display_tab(), "Display")
        self.tabs.addTab(self._resources_tab(), "Local Resources")
        self._advanced_page = self._advanced_tab()
        self.tabs.addTab(self._advanced_page, "Advanced")
        # The toggle lives in the tab row's right corner, right where the Advanced tab appears.
        self.options_btn = QPushButton()
        self.options_btn.setFlat(True)
        self.options_btn.setCursor(Qt.PointingHandCursor)
        self.options_btn.clicked.connect(lambda: self._set_options_visible(not self._options_visible))
        self.tabs.setCornerWidget(self.options_btn, Qt.TopRightCorner)
        root.addWidget(self.tabs)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)
        self.log.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.log.setMinimumWidth(LOG_WIDTH)
        self.log.setStyleSheet("font-family: monospace; font-size: 8pt;")
        self.log.setVisible(False)
        outer.addWidget(self.log, 1)  # to the right of the form, as tall as the window

        self.warn_label = QLabel()
        self.warn_label.setWordWrap(True)
        self.warn_label.setStyleSheet("color: #b36b00;")
        root.addWidget(self.warn_label)

        bar = QHBoxLayout()
        self.status = QLabel("")  # what is happening right now; left of the Connect button
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)  # never widens the window
        bar.addWidget(self.status, 1)
        self.hide_btn = QPushButton("Hide")  # only while a session is up: back to the systray
        self.hide_btn.setToolTip("Hide this window; the session keeps running")
        self.hide_btn.clicked.connect(self._enter_background)
        self.hide_btn.setVisible(False)
        bar.addWidget(self.hide_btn)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setDefault(True)
        self.connect_btn.clicked.connect(self._connect)
        bar.addWidget(self.connect_btn)
        root.addLayout(bar)

        self._refresh_clients()
        self._refresh_profiles()
        self._load_defaults()
        self._load_recent()
        if self.host.count():  # start on the server connected to most recently
            self.host.setCurrentIndex(0)
            self._recent_picked(0)
        # Enter in any logon field behaves like the Connect button.
        for edit in (self.host.lineEdit(), self.port.lineEdit(), self.username,
                     self.password, self.domain):
            edit.returnPressed.connect(self._enter_pressed)
        self._set_options_visible(False)
        for sig in self._preview_signals:
            sig.connect(self._update_preview)
        self.host.textChanged.connect(lambda *_: self._trust_timer.start())
        self.port.valueChanged.connect(lambda *_: self._trust_timer.start())
        self._refresh_trusted()

    # ------------------------------------------------------------- tabs ----
    def _general_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        box = QGroupBox("Logon settings")
        f = QFormLayout(box)
        self.host = HostCombo()
        self.host.setPlaceholderText("hostname or IP address")
        self.host.activated.connect(self._recent_picked)
        self.host.clear_requested.connect(self._clear_recent)
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(3389)
        self.port.setButtonSymbols(QSpinBox.NoButtons)  # arrows would eat the little width
        self.port.setAlignment(Qt.AlignRight)
        self.port.setToolTip("Port (default 3389)")
        self.port.setFixedWidth(self.port.fontMetrics().horizontalAdvance("65535") + 20)
        self.username = QLineEdit()
        self.domain = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.remember = QCheckBox("Allow me to save credentials")
        self.remember.setEnabled(store.keyring_available())
        if not self.remember.isEnabled():
            self.remember.setToolTip("No keyring backend available (install python3-keyring "
                                     "and a Secret Service provider)")
        computer = QHBoxLayout()  # host and port share one row: "host : 3389"
        computer.setContentsMargins(0, 0, 0, 0)
        computer.addWidget(self.host, 1)
        computer.addWidget(QLabel(":"))
        computer.addWidget(self.port)
        f.addRow("Computer:", computer)
        f.addRow("User name:", self.username)
        f.addRow("Password:", self.password)
        f.addRow("Domain:", self.domain)
        f.addRow("", self.remember)
        lay.addWidget(box)

        box2 = QGroupBox("Saved connection settings")
        v = QVBoxLayout(box2)
        self.saved = QComboBox()
        self.saved.activated.connect(self._load_selected)
        v.addWidget(self.saved)  # full width: the list of saved connections
        row = QHBoxLayout()
        for text, handler in (("Save", self._save),
                              ("Save As...", lambda: self._save(ask=True)),
                              ("Delete", self._delete)):
            btn = QPushButton(text)
            btn.clicked.connect(handler)
            # Hug the label: the style's default minimum width is what made this row wide.
            btn.setFixedWidth(btn.fontMetrics().horizontalAdvance(text) + 24)
            row.addWidget(btn)
        row.addStretch()
        v.addLayout(row)
        lay.addWidget(box2)

        box3 = QGroupBox("Troubleshooting")
        row3 = QHBoxLayout(box3)
        self.show_log = QCheckBox("Show connection log")
        self.show_log.setToolTip("Stream the FreeRDP console output below while connecting")
        self.log_level = QComboBox()
        self.log_level.addItems(["INFO", "DEBUG", "TRACE"])
        self.log_level.setCurrentText("INFO")
        self.log_level.setEnabled(False)
        self.show_log.toggled.connect(self.log_level.setEnabled)
        self.show_log.toggled.connect(self._log_toggled)
        row3.addWidget(self.show_log)
        row3.addWidget(QLabel("Level:"))
        row3.addWidget(self.log_level)
        row3.addStretch()
        lay.addWidget(box3)
        lay.addStretch()
        return w

    def _display_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        box = QGroupBox("Display configuration")
        f = QFormLayout(box)
        self.fullscreen = QCheckBox("Use full screen")
        self.resolution = QComboBox()
        self.resolution.addItems(RESOLUTIONS)
        self.resolution.currentIndexChanged.connect(self._res_changed)
        self.custom_w = QSpinBox(); self.custom_w.setRange(200, 16384); self.custom_w.setValue(1280)
        self.custom_h = QSpinBox(); self.custom_h.setRange(200, 16384); self.custom_h.setValue(720)
        cust = QHBoxLayout()
        cust.addWidget(self.custom_w); cust.addWidget(QLabel("x")); cust.addWidget(self.custom_h)
        self.custom_row = QWidget(); self.custom_row.setLayout(cust)
        self.custom_row.setVisible(False)
        self.monitors = QLineEdit()
        self.monitors.setPlaceholderText("e.g. 0,1")
        self.monitors.setToolTip("Comma-separated monitor numbers; empty = primary monitor only.\n"
                                 "Press Detect to see the numbers the selected FreeRDP client uses.")
        self.monitors.setMaximumWidth(200)  # a few digits; the room goes to the Detect button
        detect = QPushButton("Detect")
        detect.setToolTip("List the monitors the selected FreeRDP client can see")
        detect.clicked.connect(self._detect_monitors)
        monitors_row = QHBoxLayout()
        monitors_row.setContentsMargins(0, 0, 0, 0)
        monitors_row.addWidget(self.monitors)
        monitors_row.addWidget(detect)
        monitors_row.addStretch()
        self.multimon = QCheckBox("Force multi-monitor mode")
        self.dynres = QCheckBox("Resize remote desktop with the window (dynamic resolution)")
        self.dynres.setChecked(True)
        self.smart = QCheckBox("Smart sizing (scale instead of scroll)")
        # FreeRDP rejects the combination, so make the two checkboxes exclusive.
        self.dynres.toggled.connect(lambda on: on and self.smart.setChecked(False))
        self.smart.toggled.connect(lambda on: on and self.dynres.setChecked(False))
        self.depth = _combo(COLOR_DEPTHS)
        f.addRow(self.fullscreen)
        f.addRow("Remote desktop size:", self.resolution)
        f.addRow("", self.custom_row)
        f.addRow("Monitors:", monitors_row)
        f.addRow(self.multimon)
        f.addRow(self.dynres)
        f.addRow(self.smart)
        f.addRow("Colors:", self.depth)
        lay.addWidget(box)

        box = QGroupBox("Experience")
        f = QFormLayout(box)
        self.h264 = _combo(H264)
        f.addRow("H.264 graphics codec:", self.h264)
        self.h264_note = QLabel("")  # why the setting is unavailable, when it is
        self.h264_note.setWordWrap(True)
        self.h264_note.setStyleSheet("color: #b36b00;")
        self.h264_note.setVisible(False)
        f.addRow(self.h264_note)
        lay.addWidget(box)
        lay.addStretch()
        return w

    def _resources_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        box = QGroupBox("Local devices and resources")
        v = QVBoxLayout(box)
        self.clipboard = QCheckBox("Clipboard"); self.clipboard.setChecked(True)
        self.sound = QCheckBox("Play remote audio on this computer")
        self.mic = QCheckBox("Redirect microphone")
        self.home = QCheckBox("Share home folder")
        for c in (self.clipboard, self.sound, self.mic, self.home):
            v.addWidget(c)
        lay.addWidget(box)

        box2 = QGroupBox("Shared folders")
        v2 = QVBoxLayout(box2)
        self.drives = QTableWidget(0, 2)
        self.drives.setHorizontalHeaderLabels(["Name", "Local path"])
        self.drives.horizontalHeader().setStretchLastSection(True)
        self.drives.setSelectionBehavior(QAbstractItemView.SelectRows)
        v2.addWidget(self.drives)
        row = QHBoxLayout()
        add = QPushButton("Add..."); add.clicked.connect(self._add_drive)
        rem = QPushButton("Remove"); rem.clicked.connect(self._remove_drive)
        row.addWidget(add); row.addWidget(rem); row.addStretch()
        v2.addLayout(row)
        lay.addWidget(box2)
        return w

    def _advanced_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        box = QGroupBox("FreeRDP client")
        f = QFormLayout(box)
        self.client_combo = QComboBox()
        self.client_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.client_combo.setMinimumContentsLength(18)  # the long path label must not widen the window
        self.client_combo.currentIndexChanged.connect(self._update_preview)
        rescan = QPushButton("Rescan"); rescan.clicked.connect(self._refresh_clients)
        browse = QPushButton("Browse..."); browse.clicked.connect(self._browse_client)
        row = QHBoxLayout()
        row.addWidget(self.client_combo, 1); row.addWidget(rescan); row.addWidget(browse)
        f.addRow(row)
        lay.addWidget(box)

        box = QGroupBox("Connection")
        f = QFormLayout(box)
        self.security = _combo(SECURITY)
        self.cert_mode = _combo(CERT_MODES)
        self.cert_mode.setToolTip("What to do when the server presents a certificate FreeRDP "
                                  "cannot verify (usually self-signed)")
        self.trusted = QListWidget()
        self.trusted.setMaximumHeight(60)
        self.trusted.setToolTip("SHA-256 fingerprints you chose to trust for this connection")
        forget = QPushButton("Forget selected")
        forget.clicked.connect(self._forget_trusted)
        trust_box = QVBoxLayout()
        trust_box.addWidget(self.trusted); trust_box.addWidget(forget, alignment=Qt.AlignRight)
        self.reconnect = QCheckBox("Reconnect if the connection drops")
        self.reconnect.setChecked(True)
        self.retries = QSpinBox(); self.retries.setRange(1, 100); self.retries.setValue(5)
        self.retries.setFixedWidth(62)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(0, 600)
        self.timeout_spin.setSuffix(" s")
        self.timeout_spin.setSpecialValueText("No limit")
        self.timeout_spin.setFixedWidth(86)
        timeout_tip = ("Stop connecting if the remote desktop is not up after this long. Some "
                       "servers (or non-RDP services) accept the connection and then never answer.")
        self.timeout_spin.setToolTip(timeout_tip)
        self.timeout_spin.setValue(int(store.get_setting("connect_timeout", 30)))
        self.timeout_spin.valueChanged.connect(lambda v: store.set_setting("connect_timeout", v))
        self.hide_on_connect = QCheckBox("Hide this window (in systray) while a session is connected")
        self.hide_on_connect.setToolTip(
            "Like the Windows client: the window goes away once the remote desktop is up and "
            "returns when the session ends. A tray icon lets you bring it back or disconnect.\n"
            "Untick it to keep this window (and the connection log) visible.")
        self.hide_on_connect.setChecked(bool(store.get_setting("hide_on_connect", True)))
        self.hide_on_connect.toggled.connect(lambda on: store.set_setting("hide_on_connect", on))
        self.extra = QLineEdit()
        self.extra.setPlaceholderText("extra FreeRDP arguments, passed verbatim")
        f.addRow("Security:", self.security)
        f.addRow("Server certificate:", self.cert_mode)
        f.addRow("Trusted certificates:", trust_box)
        f.addRow(self.reconnect)
        limits = QHBoxLayout()  # both limits share one row below the checkbox
        limits.setContentsMargins(0, 0, 0, 0)
        give_up = QLabel("Give up after:")
        give_up.setToolTip(timeout_tip)
        limits.addWidget(QLabel("Max retries:"))
        limits.addWidget(self.retries)
        limits.addSpacing(18)
        limits.addWidget(give_up)
        limits.addWidget(self.timeout_spin)
        limits.addStretch()
        f.addRow(limits)
        f.addRow(self.hide_on_connect)
        f.addRow("Extra arguments:", self.extra)
        lay.addWidget(box)

        self.fb_box = QGroupBox("Connection bar (floatbar)")
        self.fb_box.setCheckable(True)
        self.fb_box.setChecked(True)
        row = QHBoxLayout(self.fb_box)
        self.fb_sticky = QCheckBox("Sticky"); self.fb_sticky.setChecked(True)
        self.fb_visible = QCheckBox("Visible by default"); self.fb_visible.setChecked(True)
        self.fb_show = _combo(FLOATBAR_SHOW)
        row.addWidget(self.fb_sticky)
        row.addWidget(self.fb_visible)
        row.addWidget(QLabel("Show:"))
        row.addWidget(self.fb_show, 1)
        lay.addWidget(self.fb_box)

        lay.addWidget(QLabel("Command preview (password is passed via stdin and masked here):"))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(70)
        lay.addWidget(self.preview)
        lay.addStretch()

        self._preview_signals = [
            self.host.textChanged, self.port.valueChanged, self.username.textChanged,
            self.domain.textChanged, self.fullscreen.toggled, self.resolution.currentIndexChanged,
            self.custom_w.valueChanged, self.custom_h.valueChanged, self.monitors.textChanged,
            self.multimon.toggled, self.dynres.toggled, self.smart.toggled,
            self.depth.currentIndexChanged, self.clipboard.toggled, self.sound.toggled,
            self.mic.toggled, self.home.toggled, self.h264.currentIndexChanged,
            self.security.currentIndexChanged, self.cert_mode.currentIndexChanged, self.reconnect.toggled,
            self.retries.valueChanged, self.extra.textChanged,
            self.fb_box.toggled, self.fb_sticky.toggled, self.fb_visible.toggled,
            self.fb_show.currentIndexChanged, self.drives.itemChanged,
            self.show_log.toggled, self.log_level.currentIndexChanged,
        ]
        return w

    # ------------------------------------------------- profile <-> form ----
    def _profile(self) -> Profile:
        res = self.resolution.currentText()
        w = h = None
        if res == "Custom...":
            w, h = self.custom_w.value(), self.custom_h.value()
        elif "x" in res and res[0].isdigit():
            w, h = (int(x) for x in res.split("x"))
        monitors = [int(x) for x in self.monitors.text().replace(" ", "").split(",") if x.isdigit()]
        drives = []
        for r in range(self.drives.rowCount()):
            name, path = self.drives.item(r, 0), self.drives.item(r, 1)
            if name and path and name.text() and path.text():
                drives.append(Drive(name.text(), path.text()))
        try:
            extra = shlex.split(self.extra.text())
        except ValueError:
            extra = self.extra.text().split()
        floatbar = None
        if self.fb_box.isChecked():
            floatbar = Floatbar(self.fb_sticky.isChecked(), self.fb_visible.isChecked(),
                                self.fb_show.currentData())
        return Profile(
            host=self.host.text().strip(), port=self.port.value(),
            username=self.username.text().strip(), domain=self.domain.text().strip(),
            password=self.password.text(),
            fullscreen=self.fullscreen.isChecked(), width=w, height=h,
            monitors=monitors, multimon=self.multimon.isChecked(),
            dynamic_resolution=self.dynres.isChecked(), smart_sizing=self.smart.isChecked(),
            color_depth=self.depth.currentData(),
            clipboard=self.clipboard.isChecked(), sound=self.sound.isChecked(),
            microphone=self.mic.isChecked(), drives=drives, home_drive=self.home.isChecked(),
            gfx_h264=self.h264.currentData(), security=self.security.currentData(),
            cert_mode=self.cert_mode.currentData(), trusted_fingerprints=self._trusted(),
            auto_reconnect=self.reconnect.isChecked(),
            auto_reconnect_retries=self.retries.value(), floatbar=floatbar,
            show_log=self.show_log.isChecked(), log_level=self.log_level.currentText(),
            extra_args=extra,
        )

    def _apply(self, p: Profile) -> None:
        self.host.setText(p.host); self.port.setValue(p.port)
        self.username.setText(p.username); self.domain.setText(p.domain)
        self.password.setText(p.password)
        self.remember.setChecked(bool(p.password))
        self.fullscreen.setChecked(p.fullscreen)
        if p.width and p.height:
            label = f"{p.width}x{p.height}"
            idx = self.resolution.findText(label)
            if idx < 0:
                idx = self.resolution.findText("Custom...")
                self.custom_w.setValue(p.width); self.custom_h.setValue(p.height)
            self.resolution.setCurrentIndex(idx)
        else:
            self.resolution.setCurrentIndex(0)
        self.monitors.setText(",".join(str(m) for m in p.monitors))
        self.multimon.setChecked(p.multimon); self.dynres.setChecked(p.dynamic_resolution)
        self.smart.setChecked(p.smart_sizing)
        self.depth.setCurrentIndex(max(0, self.depth.findData(p.color_depth)))
        self.clipboard.setChecked(p.clipboard); self.sound.setChecked(p.sound)
        self.mic.setChecked(p.microphone); self.home.setChecked(p.home_drive)
        self.drives.setRowCount(0)
        for d in p.drives:
            self._append_drive(d.name, d.path)
        self.h264.setCurrentIndex(max(0, self.h264.findData(p.gfx_h264)))
        self.security.setCurrentIndex(max(0, self.security.findData(p.security)))
        self.cert_mode.setCurrentIndex(max(0, self.cert_mode.findData(p.cert_mode)))
        self._profile_fps = list(p.trusted_fingerprints)
        self._refresh_trusted()
        self.reconnect.setChecked(p.auto_reconnect); self.retries.setValue(p.auto_reconnect_retries)
        self.show_log.setChecked(p.show_log); self.log_level.setCurrentText(p.log_level)
        self.extra.setText(shlex.join(p.extra_args))
        self.fb_box.setChecked(p.floatbar is not None)
        if p.floatbar:
            self.fb_sticky.setChecked(p.floatbar.sticky)
            self.fb_visible.setChecked(p.floatbar.default_visible)
            self.fb_show.setCurrentIndex(max(0, self.fb_show.findData(p.floatbar.show)))
        self._update_preview()

    # ------------------------------------------------------------ slots ----
    def _res_changed(self) -> None:
        self.custom_row.setVisible(self.resolution.currentText() == "Custom...")

    def _set_options_visible(self, visible: bool) -> None:
        """Show or hide the Advanced tab; General, Display and Local Resources stay put."""
        self._options_visible = visible
        advanced = self.tabs.indexOf(self._advanced_page)
        self.tabs.setTabVisible(advanced, visible)
        if not visible and self.tabs.currentIndex() == advanced:
            self.tabs.setCurrentIndex(0)
        self.options_btn.setText("Hide advanced \u25b4" if visible else "Show advanced \u25be")
        # QTabWidget sizes itself to its biggest page: while Advanced is hidden, let it be
        # ignored so the window only has to fit the three everyday tabs.
        policy = QSizePolicy.Preferred if visible else QSizePolicy.Ignored
        self._advanced_page.setSizePolicy(policy, policy)
        self.tabs.updateGeometry()
        self._fit()

    def _fit(self) -> None:
        """Resize the window vertically to match the current content.

        Qt's cached minimum size is stale right after tabs are hidden or shown (it only
        updates once the event loop has handled the pending layout request), so fit once
        now and again when the layout has settled."""
        self._apply_fit()
        QTimer.singleShot(0, self._apply_fit)

    def _apply_fit(self) -> None:
        self.layout().invalidate()
        self.layout().activate()
        margins = self.layout().contentsMargins()
        if self._options_visible:  # grow to fit the tabs, never shrink what the user chose
            # The form needs what the tab row needs (all tabs plus the options button). That is
            # the form's own minimum, so the log panel beside it can never take the room: the
            # window grows by exactly the difference.
            tab_row = self.tabs.tabBar().sizeHint().width() + self.options_btn.sizeHint().width()
            form = max(FORM_MIN_WIDTH, tab_row + TAB_ROW_CHROME - margins.left() - margins.right())
            self._form.setMinimumWidth(form)
            self.layout().invalidate()
            self.layout().activate()
            width = max(self.width(), self.minimumSizeHint().width())
            size = (width, max(self.height(), self.sizeHint().height()))
        else:  # collapsed: back to the size of the General tab (plus the log panel if shown)
            self._form.setMinimumWidth(FORM_MIN_WIDTH)
            self.layout().invalidate()
            self.layout().activate()
            size = (self.sizeHint().width(), self.minimumSizeHint().height())
        self.resize(*size)

    def _log_toggled(self, on: bool) -> None:
        # Grow or shrink the window sideways by the panel's width. Qt enlarges the window
        # to its new minimum width as soon as the panel appears, so remember the old width.
        before = self.width()
        was_visible = self.log.isVisible()
        self.log.setVisible(on)
        extra = LOG_WIDTH + self.layout().spacing()
        if on and not was_visible:
            self.resize(before + extra, self.height())
        elif not on and was_visible:
            self.layout().invalidate()
            self.layout().activate()
            self.resize(max(self.minimumSizeHint().width(), before - extra), self.height())
        self._fit()

    def _refresh_profiles(self) -> None:
        self.saved.clear()
        self.saved.addItem(DEFAULTS_LABEL)  # always first: the user's own defaults
        self.saved.addItems(store.list_profiles())

    def _profile_name(self) -> str:
        """The selected saved connection, or '' while 'My defaults' is selected."""
        return self.saved.currentText() if self.saved.currentIndex() > 0 else ""

    def _preferred_client_path(self) -> str | None:
        return store.load_defaults()[1]

    def _load_defaults(self) -> None:
        """Set every option to the user's defaults; the logon fields stay as they are."""
        defaults, client = store.load_defaults()
        for field in ("host", "port", "username", "domain", "password"):
            setattr(defaults, field, getattr(self._profile(), field))
        remember = self.remember.isChecked()
        self._apply(defaults)
        self.remember.setChecked(remember)
        if client:
            for i, c in enumerate(self.clients):
                if c.path == client:
                    self.client_combo.setCurrentIndex(i)
                    break
        self._sync_h264_support()

    def _save_defaults(self) -> None:
        client = self._client()
        try:
            store.save_defaults(self._profile(), client.path if client else None)
        except OSError as e:
            QMessageBox.warning(self, "Defaults not saved", f"Could not write the settings: {e}")
            return
        self.status.setText("Saved as your defaults")

    def _load_selected(self) -> None:
        name = self._profile_name()
        if not name:
            self._load_defaults()
            return
        try:
            profile = store.load_profile(name)
            self._apply(profile)
            if not profile.password:  # none under this name: maybe saved for the server itself
                self._prefill_from_saved(profile.host, profile.port, profile.username)
        except store.CredentialStoreError as e:
            self._apply(store.load_profile(name, with_password=False))
            self.remember.setChecked(True)  # keep the stored entry on the next save
            QMessageBox.warning(self, "Saved password unavailable",
                                f"The connection was loaded, but {e}.\n\n"
                                "Enter the password manually.")

    def _save(self, ask: bool = False) -> None:
        name = self._profile_name()
        if not ask and not name:  # "My defaults" is selected: Save updates the defaults
            self._save_defaults()
            return
        if ask or not name:
            name, ok = self._ask_name(name or self.host.text())
            if not ok or not name.strip():
                return
        self._store_profile(name.strip())
        self._refresh_profiles()
        self.saved.setCurrentText(name.strip())

    def _ask_name(self, text: str) -> tuple[str, bool]:
        """The Save As name prompt, 60% wider than Qt's default so the title and a long
        name are readable."""
        dialog = QInputDialog(self)
        dialog.setWindowTitle("Save connection")
        dialog.setLabelText("Name:")
        dialog.setTextValue(text)
        dialog.setMinimumWidth(int(dialog.sizeHint().width() * 1.6))
        dialog.resize(dialog.minimumWidth(), dialog.sizeHint().height())
        ok = dialog.exec() == QInputDialog.Accepted
        return dialog.textValue(), ok

    def _store_profile(self, name: str) -> None:
        """Save the form as a connection, telling the user if the keyring part failed."""
        try:
            store.save_profile(name, self._profile(), self.remember.isChecked())
        except store.CredentialStoreError as e:
            QMessageBox.warning(self, "Password not saved",
                                f"The connection '{name}' was saved, but {e}.\n\n"
                                "You will need to enter the password each time.")

    def _delete(self) -> None:
        name = self._profile_name()
        if not name:
            if QMessageBox.question(self, "Reset defaults",
                                    "Reset your defaults to the factory settings?") == QMessageBox.Yes:
                store.reset_defaults()
                self._load_defaults()
            return
        if name and QMessageBox.question(self, "Delete", f"Delete '{name}'?") == QMessageBox.Yes:
            try:
                store.delete_profile(name)
            except store.CredentialStoreError as e:
                QMessageBox.warning(self, "Password not removed",
                                    f"The connection was deleted, but {e}.")
            self._refresh_profiles()

    def _append_drive(self, name: str, path: str) -> None:
        r = self.drives.rowCount()
        self.drives.insertRow(r)
        self.drives.setItem(r, 0, QTableWidgetItem(name))
        self.drives.setItem(r, 1, QTableWidgetItem(path))

    def _add_drive(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Share folder")
        if path:
            self._append_drive(path.rstrip("/").rsplit("/", 1)[-1] or "share", path)

    def _remove_drive(self) -> None:
        for idx in sorted({i.row() for i in self.drives.selectedIndexes()}, reverse=True):
            self.drives.removeRow(idx)

    def _refresh_clients(self) -> None:
        self._set_clients(detect_clients(store.client_paths()))

    def _browse_client(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select FreeRDP client")
        if not path:
            return
        found = detect_clients([path])
        if not any(os.path.realpath(c.path) == os.path.realpath(path) for c in found):
            QMessageBox.warning(self, "Not a FreeRDP client",
                                f"{path} did not report a FreeRDP version with --version.")
            return
        store.add_client_path(path)
        self._set_clients(detect_clients(store.client_paths()), select=path)

    def _set_clients(self, clients: list[FreeRDPClient], select: str | None = None) -> None:
        self.clients = clients
        self.client_combo.blockSignals(True)
        self.client_combo.clear()
        for c in clients:
            self.client_combo.addItem(c.label, c)
        if not clients:
            self.client_combo.addItem("No FreeRDP client found (install freerdp2-x11 or freerdp3-x11)")
        if select:
            for i, c in enumerate(clients):
                if c.path == select:
                    self.client_combo.setCurrentIndex(i)
        self.client_combo.blockSignals(False)
        if hasattr(self, "preview"):
            self._update_preview()

    def _client(self) -> FreeRDPClient | None:
        return self.client_combo.currentData()

    def _sync_h264_support(self) -> None:
        """Disable the H.264 setting for a client built without it. The chosen value is kept
        (a saved connection must not lose it); the command just leaves it out."""
        client = self._client()
        supported = client is None or client.h264
        self.h264.setEnabled(supported)
        self.h264_note.setVisible(not supported)
        if not supported:
            self.h264_note.setText(f"Not available: FreeRDP {client.version} ({client.flavor}) "
                                   "was built without H.264 support.")

    def _update_preview(self, *_) -> None:
        self._sync_h264_support()
        client = self._client()
        if not client:
            self.preview.setPlainText("")
            self.warn_label.setText("")
            return
        built = build_args(self._profile(), client)
        self.preview.setPlainText(shlex.join(built.display_command(client)))
        self.warn_label.setText("\n".join(built.warnings))

    # ------------------------------------------------------ recent servers ----
    def _load_recent(self) -> None:
        self.host.set_recent(store.recent_servers())

    def _recent_picked(self, index: int) -> None:
        """Choosing a recent server fills in its port and last user name, like Windows."""
        entry = self.host.itemData(index)
        if not isinstance(entry, dict):
            return
        self.host.setText(entry["host"])  # the list shows host:port, the field takes the host
        self.port.setValue(entry["port"])
        self.username.setText(entry["username"])
        self.password.clear()  # never carry one server's password over to another
        self.remember.setChecked(False)
        if entry.get("remember"):
            self._restore_remembered_password(entry["host"], entry["port"])
        else:  # not remembered for the server, but a saved connection may know this user
            self._prefill_from_saved(entry["host"], entry["port"], entry["username"])

    def _use_remembered_password(self, p: Profile) -> None:
        """Connect with a typed server that has a remembered password, without a prompt."""
        target = store.server_label(p.host, p.port).lower()
        for entry in store.recent_servers():
            if (entry["remember"] and store.server_label(entry["host"], entry["port"]).lower() == target
                    and (not p.username or p.username == entry["username"])):
                self._restore_remembered_password(entry["host"], entry["port"])
                if self.password.text():
                    p.password = self.password.text()
                    p.username = p.username or entry["username"]
                    self.username.setText(p.username)
                return
        if p.username and self._prefill_from_saved(p.host, p.port, p.username):
            p.password = self.password.text()

    def _prefill_from_saved(self, host: str, port: int, username: str) -> bool:
        """Fill in a password already saved for exactly this server and user (see
        store.find_saved_password) and tick 'Allow me to save credentials', since the
        password is evidently stored."""
        try:
            password = store.find_saved_password(host, port, username)
        except store.CredentialStoreError as e:
            QMessageBox.warning(self, "Saved password unavailable",
                                f"A saved password exists for this server, but {e}.\n\n"
                                "Enter the password manually.")
            return False
        if not password:
            return False
        self.password.setText(password)
        self.remember.setChecked(True)
        return True

    def _restore_remembered_password(self, host: str, port: int) -> None:
        try:
            password = store.server_password(host, port)
        except store.CredentialStoreError as e:
            self.remember.setChecked(True)  # the entry still exists; don't drop it on the next connect
            QMessageBox.warning(self, "Saved password unavailable",
                                f"The server was selected, but {e}.\n\nEnter the password manually.")
            return
        if password:
            self.password.setText(password)
            self.remember.setChecked(True)

    def _clear_recent(self) -> None:
        try:
            store.clear_recent_servers()
        except store.CredentialStoreError as e:
            QMessageBox.warning(self, "Passwords not removed",
                                f"The history was cleared, but {e}.")
        self._load_recent()

    # ------------------------------------------------- certificates ----
    def _trusted(self) -> list[str]:
        return [self.trusted.item(i).text() for i in range(self.trusted.count())]

    def _refresh_trusted(self) -> None:
        """Show what is trusted for the server in the Computer field: whatever came with a
        loaded saved connection plus everything remembered for this server."""
        host, port = self.host.text().strip(), self.port.value()
        shown = list(dict.fromkeys([*self._profile_fps, *store.trusted_certificates(host, port)]))
        if shown != self._trusted():
            self.trusted.clear()
            self.trusted.addItems(shown)
        self._update_preview()

    def _forget_trusted(self) -> None:
        host, port = self.host.text().strip(), self.port.value()
        for item in self.trusted.selectedItems():
            fp = item.text()
            if fp in self._profile_fps:
                self._profile_fps.remove(fp)  # a saved connection drops it on its next Save
            store.forget_certificate(host, port, fp)
        self._refresh_trusted()

    def _remember_fingerprint(self, fp: str) -> None:
        store.trust_certificate(self.host.text().strip(), self.port.value(), fp)
        self._refresh_trusted()
        name = self._profile_name()
        if name:  # a saved connection also keeps it with its own settings
            self._store_profile(name)

    def _on_certificate_prompt(self, output: str) -> None:
        self._cert = parse_certificate_prompt(output)

    def _ask_trust(self, cert: CertInfo) -> None:
        changed = bool(self._trusted())
        details = [("Name", cert.common_name or cert.subject), ("Issuer", cert.issuer),
                   ("Valid from", cert.valid_from), ("Valid to", cert.valid_to)]  # v2 omits dates
        text = (f"The server {cert.host or self.host.text()} presented a certificate that "
                f"could not be verified.\n\n"
                + "".join(f"{k + ':':<12}{v}\n" for k, v in details if v)
                + f"\nSHA-256 fingerprint:\n{cert.thumbprint_display}")
        if changed:
            text += ("\n\nWARNING: this connection already has trusted certificates and this "
                     "is a different one. Only continue if you expected the server to change.")
        box = QMessageBox(QMessageBox.Warning if changed else QMessageBox.Question,
                          "Trust server certificate?", text, parent=self)
        once = box.addButton("Trust once", QMessageBox.AcceptRole)
        remember = box.addButton("Trust and remember", QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked not in (once, remember):
            return
        if clicked is remember:
            self._remember_fingerprint(cert.thumbprint)
        self._connect(trust_once=cert.thumbprint, keep_log=True)

    def _enter_pressed(self) -> None:
        # Enter starts a connection like the Connect button, but must never cancel or
        # disconnect a running one (the same button turns into Cancel/Disconnect).
        # The combo box and spin box re-send the key to their inner text box, so one key
        # press arrives twice: act on the first, ignore the repeat, and do the work on the
        # next event-loop turn so a modal dialog can't sit in between the two.
        if self._enter_pending or self.runner.running():
            return
        self._enter_pending = True
        QTimer.singleShot(0, self._enter_connect)

    def _enter_connect(self) -> None:
        self._enter_pending = False
        if not self.runner.running():
            self._connect()

    def _detect_monitors(self) -> None:
        """Ask the selected FreeRDP client which monitors it sees and show the answer."""
        client = self._client()
        if not client:
            QMessageBox.warning(self, "FreeRDP not found",
                                "No FreeRDP client was found. Install freerdp2-x11 or "
                                "freerdp3-x11, or use Advanced > Browse.")
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            monitors, raw = detect_monitors(client)
        except (OSError, subprocess.SubprocessError) as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Monitor detection failed",
                                f"Could not run {client.path}:\n{e}")
            return
        QApplication.restoreOverrideCursor()
        if monitors:
            title = "Detected monitors"
            text = "\n".join(m.describe() for m in monitors)
            hint = ("Type the numbers to use in the Monitors field, separated by commas "
                    "(for example 0,1). Leave it empty to use the primary monitor only.\n\n"
                    f"Numbering comes from the selected client: {client.label.split(' - ')[0]}.")
        else:
            title = "No monitors found"
            text = "The selected FreeRDP client did not report any monitors."
            hint = "Its own output is available under Show Details."
        box = QMessageBox(QMessageBox.Information, title, text, parent=self)
        box.setInformativeText(hint)
        if raw:
            box.setDetailedText(raw)
        box.exec()

    def _target(self, p: Profile) -> str:
        """host:port as shown in the status line (a port typed into Computer wins)."""
        return p.host if ":" in p.host else f"{p.host}:{p.port}"

    def _ask_credentials(self, target: str, username: str) -> tuple[str, str] | None:
        dialog = CredentialsDialog(self, target, username)
        return dialog.credentials() if dialog.exec() == QDialog.Accepted else None

    def _connect(self, trust_once: str | None = None, keep_log: bool = False) -> None:
        if self.runner.running():  # button currently reads "Cancel" or "Disconnect"
            self.connect_btn.setEnabled(False)
            self.connect_btn.setText("Disconnecting..." if self._session_up else "Cancelling...")
            self.runner.cancel()
            return
        client = self._client()
        if not client:
            QMessageBox.warning(self, "FreeRDP not found",
                                "No FreeRDP client was found. Install freerdp2-x11 or "
                                "freerdp3-x11, or use Advanced > Browse.")
            return
        p = self._profile()
        if not p.host:
            QMessageBox.warning(self, "Computer required", "Enter a computer name or address.")
            return
        if not p.password:
            self._use_remembered_password(p)
        if not p.username or not p.password:
            # FreeRDP would try to prompt on a terminal it does not have and fail confusingly.
            creds = self._ask_credentials(self._target(p), p.username)
            if creds is None:
                return
            p.username, p.password = creds
            self.username.setText(p.username)
            self.password.setText(p.password)
        if trust_once and normalize_fingerprint(trust_once) not in p.trusted_fingerprints:
            p.trusted_fingerprints.append(normalize_fingerprint(trust_once))
        self._cert = None
        self._attempt_server = (p.host, p.port, p.username)  # recorded once it connects
        built = build_args(p, client)
        if not keep_log:
            self.log.clear()
        if p.show_log:
            self.log.appendPlainText("$ " + shlex.join(built.display_command(client)) + "\n")
        self._begin_attempt(p)
        self._attempt_credentials = (p.host, p.port, p.password, self.remember.isChecked())
        self.connect_btn.setText("Cancel")
        self.runner.start(client, built)

    # ----------------------------------------------------- status line ----
    def _set_status(self, text: str, kind: str = "neutral") -> None:
        color = {"ok": "color: #3d9a50;", "error": "color: #d9534f;"}.get(kind, "")
        self.status.setStyleSheet(color)
        self.status.setText(text)
        self.status.setToolTip(text)  # the label clips instead of widening the window

    def _begin_attempt(self, p: Profile) -> None:
        self._session_up = False
        self.hide_btn.setVisible(False)
        self._timed_out = False
        limit = self.timeout_spin.value()
        self._attempt = Attempt(self._target(p), p.username, p.security, p.cert_mode, limit)
        self._t0 = time.monotonic()
        self._update_elapsed()
        self._tick.start()
        if limit > 0:
            self._timeout_timer.start(limit * 1000)

    def _update_elapsed(self) -> None:
        if self._attempt:
            seconds = int(time.monotonic() - self._t0)
            self._set_status(f"Connecting to {self._attempt.target} ... {seconds} s")

    def _stop_timers(self) -> None:
        self._tick.stop()
        self._timeout_timer.stop()

    def _apply_credential_choice(self) -> None:
        """After a successful logon: keep the password for this server if the user allowed
        it, or forget one kept earlier if they unticked the box. Doing it only now means a
        mistyped password is never stored."""
        if not self._attempt_credentials:
            return
        host, port, password, remember = self._attempt_credentials
        self._attempt_credentials = None
        if self._attempt_server:  # only servers that really connected enter the Computer list
            store.record_recent_server(*self._attempt_server)
            self._attempt_server = None
        try:
            if remember and password:
                store.remember_server_password(host, port, password)
            elif not remember:
                store.forget_server_password(host, port)
        except store.CredentialStoreError as e:
            QMessageBox.warning(self, "Password not saved",
                                f"You are connected, but {e}.\n\n"
                                "You will need to enter the password next time.")
        self._load_recent()

    def _on_timeout(self) -> None:
        if self.runner.running() and not self._session_up:
            self._timed_out = True
            self.runner.cancel()

    def _on_connected(self) -> None:
        self._stop_timers()
        self._session_up = True
        self.hide_btn.setVisible(True)
        self.connect_btn.setText("Disconnect")
        if self._attempt:
            self._set_status(f"Connected to {self._attempt.target}", "ok")
        self._apply_credential_choice()
        if self.show_log.isChecked():
            self.log.appendPlainText("\n[connected]")
        if self.hide_on_connect.isChecked():
            self._enter_background()

    # ----------------------------------------- hide while a session is up ----
    def _enter_background(self) -> None:
        """Get out of the way once the remote desktop is up, but stay reachable."""
        self._backgrounded = True
        if QSystemTrayIcon.isSystemTrayAvailable():
            if self.tray is None:
                self.tray = self._build_tray()
            target = self.host.text().strip()
            self.tray.setToolTip(f"FreeRDC - connected to {target}")
            self._tray_info.setText(f"Connected to {target}")
            self.tray.show()
            self.hide()
        else:
            self.showMinimized()  # no tray: stay reachable from the task bar

    def _leave_background(self) -> None:
        if not self._backgrounded:
            return
        self._backgrounded = False
        if self.tray:
            self.tray.hide()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _build_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(app_icon(), self)
        menu = QMenu(self)
        self._tray_info = QAction("", menu)  # information only: greyed out, does nothing
        self._tray_info.setEnabled(False)
        menu.addAction(self._tray_info)
        menu.addSeparator()
        show = QAction("Show FreeRDC", menu)
        show.triggered.connect(self._leave_background)
        disconnect = QAction("Disconnect", menu)
        disconnect.triggered.connect(self.runner.cancel)
        quit_ = QAction("Quit (ends the session)", menu)
        quit_.triggered.connect(self.close)
        for a in (show, disconnect, quit_):
            menu.addAction(a)
        tray.setContextMenu(menu)
        # A left click opens the same menu as a right click (it no longer restores the window;
        # "Show FreeRDC" in the menu does that). Wayland refuses a menu that has no window of
        # ours with input focus to hang from, so there the same entries come up as a small
        # panel instead.
        self._tray_panel = _TrayPanel(self._tray_info, show, disconnect, quit_)
        tray.activated.connect(self._tray_clicked)
        self._tray_menu = menu  # keep a reference
        return tray

    def _tray_clicked(self, reason) -> None:
        if reason != QSystemTrayIcon.Trigger:
            return
        if QGuiApplication.platformName().startswith("wayland"):
            self._tray_panel.toggle()
        else:
            self._tray_menu.popup(QCursor.pos())

    def closeEvent(self, event) -> None:
        if self.tray:
            self.tray.hide()
        event.accept()
        QApplication.quit()

    def _on_output(self, text: str) -> None:
        if self.show_log.isChecked():
            self.log.moveCursor(QTextCursor.End)
            self.log.insertPlainText(text)
            self.log.moveCursor(QTextCursor.End)

    def _on_finished(self, code: int, output: str, cancelled: bool) -> None:
        self._stop_timers()
        self.connect_btn.setEnabled(True)
        self.connect_btn.setText("Connect")
        cert, self._cert = self._cert, None
        was_up, self._session_up = self._session_up, False
        self.hide_btn.setVisible(False)
        timed_out, self._timed_out = self._timed_out, False
        at = self._attempt or Attempt(target=self.host.text().strip())
        self._leave_background()  # the session is over: bring the window back
        diagnosis = (timeout_diagnosis(at) if timed_out
                     else diagnose(output, code, at, cancelled=cancelled))
        if self.show_log.isChecked():
            note = ("certificate needs confirmation" if cert else
                    "timed out" if timed_out else
                    "cancelled" if cancelled else f"FreeRDP exited with code {code}")
            self.log.appendPlainText(f"\n[{note}]")
        if cert:
            self._set_status(f"Waiting for you to confirm the certificate of {at.target}")
            # Let this slot return first so the button state is settled before the dialog.
            QTimer.singleShot(0, lambda: self._ask_trust(cert))
            return
        if was_up:  # the session ended on its own (or by Disconnect); not a connection error
            self._set_status(f"Disconnected from {at.target}")
            if diagnosis.informative:
                self._show_diagnosis(diagnosis, output)
            return
        if cancelled and not timed_out:
            self._set_status(f"Cancelled connecting to {at.target}")
            return
        if code == 0 and not timed_out:
            self._set_status(f"Disconnected from {at.target}")
            return
        self._set_status(f"Failed connecting to {at.target}", "error")
        self._show_diagnosis(diagnosis, output)

    def _show_diagnosis(self, d, output: str) -> None:
        icon = QMessageBox.Information if d.informative else QMessageBox.Warning
        box = QMessageBox(icon, d.title, d.message, parent=self)
        if d.hint:
            box.setInformativeText(d.hint)
        if output.strip():
            box.setDetailedText(output.strip())  # FreeRDP's own words, for the curious
        box.exec()
