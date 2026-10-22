import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtWidgets import QApplication

import main


class FakeBackend:
    is_simulating = False

    def __init__(self):
        self.callbacks = {}
        self.error = None

    def hook(self, callback):
        if self.error:
            raise RuntimeError(self.error)
        self.callbacks["hook"] = callback
        return "hook"

    def on_press(self, callback):
        if self.error:
            raise RuntimeError(self.error)
        self.callbacks["capture"] = callback
        return "capture"

    def unhook(self, token):
        self.callbacks.pop(token, None)

    def unhook_all(self):
        self.callbacks.clear()

    def foreground_target(self, own_window_ids=()):
        return 42


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    backend = FakeBackend()
    monkeypatch.setattr(main, "create_backend", lambda: backend)
    widget = main.VirtualKeyboardApp(enable_global_input=False, pack_dir=str(tmp_path))
    yield widget
    widget.shutdown()
    widget.tray_icon.hide()
    widget.settings_dialog.close()
    widget.close()
    app.processEvents()


def test_startup_without_global_input(window):
    assert not window.backend.callbacks
    assert not window._fg_timer.isActive()
    assert "space" in window.audio.rules
    assert "a" in window.buttons


def test_keyboard_repeat_and_simulated_input(window):
    window.audio.play_key = Mock()
    window.audio.release_key = Mock()
    window.start_keyboard_hook()
    window.start_keyboard_hook()
    callback = window.backend.callbacks["hook"]
    event = SimpleNamespace(name="a", scan_code=None, event_type="down")
    callback(event)
    callback(event)
    window.audio.play_key.assert_called_once_with("a")
    assert window.buttons["a"].property("is_pressed")
    event.event_type = "up"
    callback(event)
    window.audio.release_key.assert_called_once_with("a")
    assert not window.buttons["a"].property("is_pressed")
    window.backend.is_simulating = True
    event.event_type = "down"
    callback(event)
    window.audio.play_key.assert_called_once()


def test_permission_failure_can_retry(window):
    errors = []
    window.key_sig.error.disconnect()
    window.key_sig.error.connect(errors.append)
    window.backend.error = "Input Monitoring permission is required"
    window.start_keyboard_hook()
    assert window._hook_id is None
    assert errors == [window.backend.error]
    window.backend.error = None
    window.start_keyboard_hook()
    assert window._hook_id == "hook"


def test_capture_fallback_does_not_need_global_permission(window, app):
    window.backend.error = "No global access"
    dialog = main.KeyCaptureDialog(window.settings_dialog)
    dialog.show()
    app.processEvents()
    event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Space, Qt.NoModifier, " ")
    dialog.keyPressEvent(event)
    assert dialog.captured_key == "space"
    assert dialog.btn_ok.isEnabled()
    dialog.close()


def test_capture_unhooks_on_close(window, app):
    dialog = main.KeyCaptureDialog(window.settings_dialog)
    dialog.show()
    app.processEvents()
    window.backend.callbacks["capture"](SimpleNamespace(name="right shift", scan_code=None))
    assert dialog.captured_key == "rshift"
    dialog.close()
    assert "capture" not in window.backend.callbacks


@pytest.mark.parametrize(
    ("platform", "qt_key", "canonical"),
    [
        ("darwin", Qt.Key_Control, "win"),
        ("darwin", Qt.Key_Meta, "ctrl"),
        ("win32", Qt.Key_Control, "ctrl"),
        ("win32", Qt.Key_Meta, "win"),
    ],
)
def test_capture_fallback_modifier_names_match_native_backend(
    window, app, monkeypatch, platform, qt_key, canonical
):
    window.backend.error = "No global access"
    monkeypatch.setattr(main.sys, "platform", platform)
    dialog = main.KeyCaptureDialog(window.settings_dialog)
    dialog.show()
    app.processEvents()
    event = QKeyEvent(QKeyEvent.KeyPress, qt_key, Qt.NoModifier)
    dialog.keyPressEvent(event)
    assert dialog.captured_key == canonical
    dialog.close()


@pytest.mark.parametrize(
    ("qt_key", "canonical"),
    [(Qt.Key_F1 + offset, f"f{offset + 1}") for offset in range(12)]
    + [(Qt.Key_Insert, "ins"), (Qt.Key_Menu, "menu")],
)
def test_capture_fallback_handles_non_text_keys(window, app, qt_key, canonical):
    window.backend.error = "No global access"
    dialog = main.KeyCaptureDialog(window.settings_dialog)
    dialog.show()
    app.processEvents()
    event = QKeyEvent(QKeyEvent.KeyPress, qt_key, Qt.NoModifier, "")
    dialog.keyPressEvent(event)
    assert dialog.captured_key == canonical
    assert dialog.btn_ok.isEnabled()
    dialog.close()


def test_capture_from_listener_thread_updates_ui_on_main_thread(window, app):
    dialog = main.KeyCaptureDialog(window.settings_dialog)
    dialog.show()
    app.processEvents()
    callback = window.backend.callbacks["capture"]
    thread = threading.Thread(target=callback, args=(SimpleNamespace(name="a", scan_code=None),))
    thread.start()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert dialog.captured_key == ""
    app.processEvents()
    assert dialog.captured_key == "a"
    dialog.close()


def test_foreground_target_remembers_last_other_application(window):
    window._track_fg()
    assert window._last_fg_hwnd == 42
    window.backend.foreground_target = lambda own_window_ids: None
    window._track_fg()
    assert window._last_fg_hwnd == 42
