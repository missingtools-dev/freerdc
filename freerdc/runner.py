"""Run a FreeRDP client as a subprocess, feeding secrets over stdin."""
from __future__ import annotations

import shutil

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from .environment import child_environment
from .freerdp import BuildResult, FreeRDPClient
from .freerdp.certs import has_prompt
from .freerdp.session import session_established

KILL_AFTER_MS = 3000  # SIGKILL if SIGTERM is ignored


class Runner(QObject):
    started = Signal()
    connected = Signal()               # the remote session is up (seen once per run)
    certificate_prompt = Signal(str)   # FreeRDP is asking whether to trust a certificate
    output = Signal(str)               # live console output (stdout + stderr)
    finished = Signal(int, str, bool)  # exit code, tail of output, was_cancelled

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._output = ""
        self._cancelled = False
        self._prompted = False
        self._connected = False

    def running(self) -> bool:
        return self._proc is not None and self._proc.state() != QProcess.NotRunning

    def start(self, client: FreeRDPClient, built: BuildResult) -> None:
        cmd = built.command(client)
        self._output = ""
        self._cancelled = False
        self._prompted = False
        self._connected = False
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        environment = QProcessEnvironment()
        for key, value in child_environment().items():
            environment.insert(key, value)
        proc.setProcessEnvironment(environment)
        proc.readyRead.connect(self._on_output)
        proc.started.connect(lambda: self._feed_stdin(built))
        proc.started.connect(self.started)
        proc.errorOccurred.connect(self._on_error)
        proc.finished.connect(self._on_finished)
        self._proc = proc
        # FreeRDP prints with stdio, which block-buffers when piped; without this the
        # certificate details can sit unseen in its buffer while it waits.
        stdbuf = shutil.which("stdbuf")
        if stdbuf:
            cmd = [stdbuf, "-oL", "-eL", *cmd]
        proc.start(cmd[0], cmd[1:])

    def cancel(self) -> None:
        """Ask the client to stop; force-kill it if it doesn't within a few seconds."""
        proc = self._proc
        if not self.running():
            return
        self._cancelled = True
        proc.terminate()
        QTimer.singleShot(KILL_AFTER_MS, lambda: proc.state() != QProcess.NotRunning and proc.kill())

    def _feed_stdin(self, built: BuildResult) -> None:
        payload = built.stdin_payload()
        if payload:
            self._proc.write(payload.encode())
        self._proc.closeWriteChannel()

    def _on_output(self) -> None:
        text = bytes(self._proc.readAll()).decode(errors="replace")
        self._output = (self._output + text)[-8000:]
        self.output.emit(text)
        if not self._connected and session_established(self._output):
            self._connected = True
            self.connected.emit()
        if not self._prompted and has_prompt(self._output):
            # FreeRDP would now wait for a keypress we can't give it. Stop it and
            # let the GUI ask the user instead.
            self._prompted = True
            self.certificate_prompt.emit(self._output)
            self.cancel()

    def _on_error(self, err) -> None:
        if err == QProcess.FailedToStart:
            self.finished.emit(-1, f"Could not start FreeRDP: {self._proc.errorString()}", False)

    def _on_finished(self, code: int, _status) -> None:
        self.finished.emit(code, self._output, self._cancelled)
