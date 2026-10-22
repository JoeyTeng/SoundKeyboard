"""Lazy cross-platform keyboard hooks and synthetic key input.

Importing this module does not import native event frameworks or open hooks.
On macOS, global listening requires Input Monitoring permission and posting
keyboard events requires Accessibility permission. Secure Input can prevent
global key events from reaching an event tap; this module does not bypass it.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

KEY_DOWN = "down"
KEY_UP = "up"


class PlatformInputError(RuntimeError):
    """Base error for unavailable platform input operations."""


class InputPermissionError(PlatformInputError):
    """Raised when the operating system denies listening or event posting."""


@dataclass(frozen=True)
class KeyEvent:
    name: str
    event_type: str
    scan_code: int | None = None


_NAME_ALIASES = {
    "spacebar": "space",
    "return": "enter",
    "\r": "enter",
    "\n": "enter",
    "escape": "esc",
    "left shift": "shift",
    "lshift": "shift",
    "right shift": "rshift",
    "left ctrl": "ctrl",
    "lctrl": "ctrl",
    "left control": "ctrl",
    "control": "ctrl",
    "right ctrl": "rctrl",
    "right control": "rctrl",
    "left alt": "alt",
    "lalt": "alt",
    "right alt": "ralt",
    "altgr": "ralt",
    "left windows": "win",
    "left win": "win",
    "lwin": "win",
    "windows": "win",
    "left meta": "win",
    "cmd": "win",
    "right windows": "rwin",
    "right win": "rwin",
    "right meta": "rwin",
    "caps lock": "caps",
    "capital": "caps",
    "capslock": "caps",
    "backspace": "back",
    "delete": "del",
    "insert": "ins",
    "apps": "menu",
    "context menu": "menu",
    "option": "alt",
    "left option": "alt",
    "right option": "ralt",
    "command": "win",
    "left command": "win",
    "rcmd": "rwin",
    "right command": "rwin",
    "left meta key": "win",
    "right meta key": "rwin",
}
_SHIFTED_ASCII = dict(zip('!@#$%^&*()_+{}|:"<>?~', "1234567890-=[]\\;'.,/`"))
_SCAN_CODE_MAP = {
    42: "shift",
    54: "rshift",
    29: "ctrl",
    285: "rctrl",
    56: "alt",
    312: "ralt",
    91: "win",
    92: "rwin",
    347: "win",
    348: "rwin",
    58: "caps",
    57: "space",
    28: "enter",
    1: "esc",
    15: "tab",
    14: "back",
    339: "del",
    83: "del",
    338: "ins",
    82: "ins",
}


def normalize_key(name: Any, scan_code: int | None = None) -> str:
    """Return the app's canonical key name while avoiding macOS keycode guesses.

    ``scan_code`` is interpreted only using the legacy Windows hook table.
    macOS events carry their canonical key name and set ``scan_code`` to None,
    because macOS virtual keycodes overlap Windows scan-code values.
    """
    if scan_code is not None and scan_code in _SCAN_CODE_MAP:
        return _SCAN_CODE_MAP[scan_code]
    if not name:
        return ""
    value = str(name).strip().lower()
    value = _NAME_ALIASES.get(value, _SHIFTED_ASCII.get(value, value))
    return value


def create_backend() -> WindowsBackend | MacOSBackend:
    """Create the backend for the current OS without opening a hook."""
    if sys.platform == "win32":
        return WindowsBackend()
    if sys.platform == "darwin":
        return MacOSBackend()
    raise PlatformInputError(f"Keyboard input is not supported on {sys.platform!r}.")


class WindowsBackend:
    """Windows implementation preserving the app's existing key behavior."""

    def __init__(self) -> None:
        self._tokens: dict[object, tuple[str, Any]] = {}
        self._simulating = False
        self._simulation_lock = threading.Lock()

    @property
    def is_simulating(self) -> bool:
        return self._simulating

    def prepare(self) -> None:
        """Load the keyboard dependency without installing a hook."""
        import keyboard  # noqa: F401

    def hook(self, callback: Callable[[KeyEvent], Any]) -> object:
        import keyboard

        def dispatch(event: Any) -> None:
            event_type = KEY_DOWN if event.event_type == "down" else KEY_UP
            callback(
                KeyEvent(normalize_key(event.name, event.scan_code), event_type, event.scan_code)
            )

        handle = keyboard.hook(dispatch)
        token = object()
        self._tokens[token] = ("hook", handle)
        return token

    def on_press(self, callback: Callable[[KeyEvent], Any]) -> object:
        import keyboard

        def dispatch(event: Any) -> None:
            callback(
                KeyEvent(normalize_key(event.name, event.scan_code), KEY_DOWN, event.scan_code)
            )

        handle = keyboard.on_press(dispatch)
        token = object()
        self._tokens[token] = ("press", handle)
        return token

    def unhook(self, token: object) -> None:
        entry = self._tokens.pop(token, None)
        if entry is None:
            return
        import keyboard

        kind, handle = entry
        if kind == "hook":
            keyboard.unhook(handle)
        else:
            keyboard.unhook(handle)

    def unhook_all(self) -> None:
        import keyboard

        for _, handle in tuple(self._tokens.values()):
            keyboard.unhook(handle)
        self._tokens.clear()

    def simulate_keys(
        self, key: str, modifier_keys: Iterable[str] | None = None, target: int | None = None
    ) -> None:
        vk_map = _WINDOWS_VK_MAP
        key = normalize_key(key)
        vk = vk_map.get(key)
        if vk is None:
            return
        modifiers = [
            vk_map[normalize_key(mod)]
            for mod in (modifier_keys or ())
            if vk_map.get(normalize_key(mod))
        ]
        user32 = ctypes.windll.user32
        user32.MapVirtualKeyW.argtypes = [ctypes.c_uint, ctypes.c_uint]
        user32.MapVirtualKeyW.restype = ctypes.c_uint
        user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        user32.SetForegroundWindow.restype = ctypes.c_bool
        user32.IsWindow.argtypes = [ctypes.c_void_p]
        user32.IsWindow.restype = ctypes.c_bool
        self._simulation_lock.acquire()
        self._simulating = True
        try:
            time.sleep(0.01)
            if target and user32.IsWindow(ctypes.c_void_p(target)):
                user32.SetForegroundWindow(ctypes.c_void_p(target))
                time.sleep(0.05)
            inputs = [_windows_key_input(user32, code) for code in modifiers]
            inputs.append(_windows_key_input(user32, vk))
            inputs.append(_windows_key_input(user32, vk, 0x0002))
            for code in reversed(modifiers):
                inputs.append(_windows_key_input(user32, code, 0x0002))
            array = (_WIN_INPUT * len(inputs))(*inputs)
            user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(_WIN_INPUT), ctypes.c_int]
            user32.SendInput.restype = ctypes.c_uint
            user32.SendInput(len(inputs), array, ctypes.sizeof(_WIN_INPUT))
        finally:
            time.sleep(0.02)
            self._simulating = False
            self._simulation_lock.release()

    def foreground_target(self, own_window_ids: Iterable[int] = ()) -> int | None:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        handle = user32.GetForegroundWindow()
        value = int(handle or 0)
        if not value or value in set(own_window_ids):
            return None
        return value


_WINDOWS_VK_MAP = {
    "space": 0x20,
    "enter": 0x0D,
    "tab": 0x09,
    "back": 0x08,
    "caps": 0x14,
    "shift": 0x10,
    "rshift": 0xA1,
    "ctrl": 0x11,
    "rctrl": 0xA3,
    "alt": 0x12,
    "ralt": 0xA5,
    "win": 0x5B,
    "rwin": 0x5C,
    "menu": 0x5D,
    "esc": 0x1B,
    "ins": 0x2D,
    "del": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
}
_WINDOWS_VK_MAP.update({f"f{i}": 0x6F + i for i in range(1, 13)})
_WINDOWS_VK_MAP.update({chr(code): code - 32 for code in range(ord("a"), ord("z") + 1)})
_WINDOWS_VK_MAP.update({str(code): 0x30 + code for code in range(10)})
_WINDOWS_VK_MAP.update(
    dict(zip("-=\\[];',./`", (0xBD, 0xBB, 0xDC, 0xDB, 0xDD, 0xBA, 0xDE, 0xBC, 0xBE, 0xBF, 0xC0)))
)
_WINDOWS_EXTENDED_KEYS = {
    0xA1,
    0xA3,
    0xA5,
    0x5B,
    0x5C,
    0x5D,
    0x2D,
    0x2E,
    0x24,
    0x23,
    0x21,
    0x22,
    0x26,
    0x28,
    0x25,
    0x27,
}


class _WIN_KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _WIN_HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_uint32),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort),
    ]


class _WIN_MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _WIN_INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", _WIN_MOUSEINPUT), ("ki", _WIN_KEYBDINPUT), ("hi", _WIN_HARDWAREINPUT)]


class _WIN_INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("union", _WIN_INPUT_UNION)]


def _windows_key_input(user32: Any, vk: int, flags: int = 0) -> _WIN_INPUT:
    value = _WIN_INPUT()
    value.type = 1  # INPUT_KEYBOARD
    value.union.ki.wVk = vk
    value.union.ki.wScan = user32.MapVirtualKeyW(vk, 0)
    value.union.ki.dwFlags = flags | (1 if vk in _WINDOWS_EXTENDED_KEYS else 0)
    value.union.ki.time = 0
    value.union.ki.dwExtraInfo = 0
    return value


# Mac ANSI keyboard layout positions (virtual keycodes from Apple HIToolbox).
_MAC_KEYCODES: dict[int, str] = {
    0: "a",
    1: "s",
    2: "d",
    3: "f",
    4: "h",
    5: "g",
    6: "z",
    7: "x",
    8: "c",
    9: "v",
    11: "b",
    12: "q",
    13: "w",
    14: "e",
    15: "r",
    16: "y",
    17: "t",
    18: "1",
    19: "2",
    20: "3",
    21: "4",
    22: "6",
    23: "5",
    24: "=",
    25: "9",
    26: "7",
    27: "-",
    28: "8",
    29: "0",
    30: "]",
    31: "o",
    32: "u",
    33: "[",
    34: "i",
    35: "p",
    36: "enter",
    37: "l",
    38: "j",
    39: "'",
    40: "k",
    41: ";",
    42: "\\",
    43: ",",
    44: "/",
    45: "n",
    46: "m",
    47: ".",
    48: "tab",
    49: "space",
    50: "`",
    51: "back",
    53: "esc",
    55: "cmd",
    54: "rcmd",
    56: "shift",
    57: "caps",
    58: "alt",
    59: "ctrl",
    60: "rshift",
    61: "ralt",
    62: "rctrl",
    63: "fn",
    65: ".",
    67: "*",
    69: "+",
    71: "clear",
    75: "/",
    76: "enter",
    78: "-",
    81: "=",
    82: "0",
    83: "1",
    84: "2",
    85: "3",
    86: "4",
    87: "5",
    88: "6",
    89: "7",
    91: "8",
    92: "9",
    115: "home",
    116: "pageup",
    117: "del",
    118: "f4",
    119: "end",
    120: "f2",
    121: "pagedown",
    122: "f1",
    123: "left",
    124: "right",
    125: "down",
    126: "up",
    96: "f5",
    97: "f6",
    98: "f7",
    99: "f3",
    100: "f8",
    101: "f9",
    103: "f11",
    105: "f13",
    107: "f14",
    109: "f10",
    111: "f12",
    113: "f15",
    114: "help",
}

_MAC_MODIFIERS = {
    54: ("rcmd", "kCGEventFlagMaskCommand"),
    55: ("cmd", "kCGEventFlagMaskCommand"),
    56: ("shift", "kCGEventFlagMaskShift"),
    60: ("rshift", "kCGEventFlagMaskShift"),
    58: ("alt", "kCGEventFlagMaskAlternate"),
    61: ("ralt", "kCGEventFlagMaskAlternate"),
    59: ("ctrl", "kCGEventFlagMaskControl"),
    62: ("rctrl", "kCGEventFlagMaskControl"),
    57: ("caps", "kCGEventFlagMaskAlphaShift"),
}
_MAC_POST_KEYCODES = {
    name: code for code, name in _MAC_KEYCODES.items() if code <= 63 or code >= 96
}
_MAC_POST_KEYCODES.update(
    {
        "delete": 117,
        "backspace": 51,
        "win": 55,
        "rwin": 54,
        "alt": 58,
        "ralt": 61,
        "ctrl": 59,
        "rctrl": 62,
        "shift": 56,
        "rshift": 60,
        "caps": 57,
    }
)


class MacOSBackend:
    """macOS Quartz event tap and event posting backend.

    PyObjC is imported only when a native operation is requested. A listen-only
    tap runs on a private CoreFoundation run-loop thread and never modifies
    incoming events. Synthetic events carry a private user-data marker so this
    backend reliably excludes its own input from callbacks.
    """

    _SYNTHETIC_MARKER = 0x534B4244

    def __init__(self) -> None:
        self._tokens: dict[object, Callable[[KeyEvent], Any]] = {}
        self._tap = None
        self._source = None
        self._run_loop = None
        self._thread: threading.Thread | None = None
        self._ready: threading.Event | None = None
        self._stop_requested: threading.Event | None = None
        self._startup_error: BaseException | None = None
        self._lock = threading.RLock()
        self._simulation_lock = threading.Lock()
        self._held_keys: set[str] = set()
        self._held_modifiers: dict[int, str] = {}
        self._simulating = False
        self._quartz = None
        self._core_foundation = None
        self._appkit = None

    @property
    def is_simulating(self) -> bool:
        return self._simulating

    def prepare(self) -> None:
        """Load PyObjC frameworks without checking permissions or opening a tap."""
        self._load_native()

    def _load_native(self) -> tuple[Any, Any, Any]:
        if self._quartz is None:
            try:
                import AppKit
                import CoreFoundation
                import Quartz
            except ImportError as exc:
                raise PlatformInputError(
                    "macOS keyboard input requires pyobjc-framework-Quartz and pyobjc-framework-Cocoa."
                ) from exc
            self._quartz, self._core_foundation, self._appkit = Quartz, CoreFoundation, AppKit
        return self._quartz, self._core_foundation, self._appkit

    @staticmethod
    def _check_permission(quartz: Any, operation: str) -> None:
        preflight_name = (
            "CGPreflightListenEventAccess"
            if operation == "listen"
            else "CGPreflightPostEventAccess"
        )
        preflight = getattr(quartz, preflight_name, None)
        if preflight is not None and not preflight():
            scope = "Input Monitoring" if operation == "listen" else "Accessibility"
            raise InputPermissionError(
                f"macOS {scope} permission is required to {operation} keyboard events. "
                f"Enable it for SoundKeyboard in System Settings > Privacy & Security > {scope}."
            )

    def hook(self, callback: Callable[[KeyEvent], Any]) -> object:
        with self._lock:
            if self._thread is None:
                self._start_tap()
            token = object()
            self._tokens[token] = callback
            return token

    def on_press(self, callback: Callable[[KeyEvent], Any]) -> object:
        def press_only(event: KeyEvent) -> None:
            if event.event_type == KEY_DOWN:
                callback(event)

        return self.hook(press_only)

    def _start_tap(self) -> None:
        quartz, _, _ = self._load_native()
        self._check_permission(quartz, "listen")
        self._ready = threading.Event()
        self._stop_requested = threading.Event()
        self._startup_error = None
        self._thread = threading.Thread(
            target=self._tap_thread_main, name="SoundKeyboard-EventTap", daemon=True
        )
        self._thread.start()
        self._ready.wait(timeout=5)
        if not self._ready.is_set():
            self._stop_tap()
            raise PlatformInputError("Timed out while starting the macOS keyboard event tap.")
        if self._startup_error is not None:
            error = self._startup_error
            if self._thread is not None:
                self._thread.join(timeout=5)
            self._thread = None
            if isinstance(error, InputPermissionError):
                raise error
            raise PlatformInputError(
                f"Could not start macOS keyboard event tap: {error}"
            ) from error

    def _tap_thread_main(self) -> None:
        quartz, core_foundation, _ = self._load_native()
        down = quartz.kCGEventKeyDown
        up = quartz.kCGEventKeyUp
        flags_changed = quartz.kCGEventFlagsChanged
        mask = (1 << down) | (1 << up) | (1 << flags_changed)

        def tap_callback(proxy: Any, event_type: int, event: Any, user_info: Any) -> Any:
            try:
                if (
                    event_type == quartz.kCGEventTapDisabledByTimeout
                    or event_type == quartz.kCGEventTapDisabledByUserInput
                ):
                    self._release_held_keys()
                    if self._tap is not None:
                        quartz.CGEventTapEnable(self._tap, True)
                    return event
                marker_field = getattr(quartz, "kCGEventSourceUserData", None)
                if (
                    marker_field is not None
                    and quartz.CGEventGetIntegerValueField(event, marker_field)
                    == self._SYNTHETIC_MARKER
                ):
                    return event
                # A missed modifier release can leave tracked state behind.
                # Reconcile only keys we previously saw go down; discovering
                # arbitrary held keys here would create synthetic presses.
                self._sync_held_modifiers()
                keycode = int(
                    quartz.CGEventGetIntegerValueField(event, quartz.kCGKeyboardEventKeycode)
                )
                if event_type == flags_changed:
                    self._dispatch_modifier(keycode, event)
                elif event_type in (down, up):
                    name = _MAC_KEYCODES.get(keycode)
                    if name:
                        self._dispatch(
                            KeyEvent(name, KEY_DOWN if event_type == down else KEY_UP, None)
                        )
            except Exception:
                # Event taps must not let application callback failures escape into Quartz.
                pass
            return event

        try:
            self._tap = quartz.CGEventTapCreate(
                quartz.kCGSessionEventTap,
                quartz.kCGHeadInsertEventTap,
                quartz.kCGEventTapOptionListenOnly,
                mask,
                tap_callback,
                None,
            )
            if not self._tap:
                self._startup_error = InputPermissionError(
                    "macOS could not create a keyboard event tap. Grant Input Monitoring "
                    "permission to SoundKeyboard, then retry. Secure Input may also block listening."
                )
                self._ready.set()
                return
            self._source = core_foundation.CFMachPortCreateRunLoopSource(None, self._tap, 0)
            self._run_loop = core_foundation.CFRunLoopGetCurrent()
            core_foundation.CFRunLoopAddSource(
                self._run_loop, self._source, core_foundation.kCFRunLoopDefaultMode
            )
            quartz.CGEventTapEnable(self._tap, True)
            self._ready.set()
            if not self._stop_requested.is_set():
                core_foundation.CFRunLoopRun()
        except BaseException as exc:
            self._startup_error = exc
            if self._ready:
                self._ready.set()
        finally:
            tap, source, run_loop = self._tap, self._source, self._run_loop
            if source and run_loop:
                try:
                    core_foundation.CFRunLoopRemoveSource(
                        run_loop, source, core_foundation.kCFRunLoopDefaultMode
                    )
                except Exception:
                    pass
            if tap:
                try:
                    core_foundation.CFMachPortInvalidate(tap)
                except Exception:
                    pass
            self._tap = self._source = self._run_loop = None

    def _dispatch(self, event: KeyEvent) -> None:
        with self._lock:
            if event.event_type == KEY_DOWN:
                self._held_keys.add(event.name)
            elif event.event_type == KEY_UP:
                self._held_keys.discard(event.name)
            callbacks = tuple(self._tokens.values())
        for callback in callbacks:
            try:
                callback(event)
            except Exception:
                pass

    def _dispatch_modifier(self, keycode: int, event: Any) -> None:
        modifier = _MAC_MODIFIERS.get(keycode)
        if modifier is None:
            return
        name, _ = modifier
        # Caps Lock is a latched state, not a held modifier. Treat each
        # flags-changed event as a complete key press so it cannot stick.
        if keycode == 57:
            self._dispatch(KeyEvent(name, KEY_DOWN, None))
            self._dispatch(KeyEvent(name, KEY_UP, None))
            return
        is_down = self._physical_key_is_down(keycode)
        if is_down is None:
            # Keep a conservative compatibility fallback for Quartz wrappers
            # that lack the key-state API. Do not infer an unseen down from an
            # aggregate flag after listening starts.
            if keycode in self._held_modifiers:
                self._held_modifiers.pop(keycode, None)
                self._dispatch(KeyEvent(name, KEY_UP, None))
            return
        was_down = keycode in self._held_modifiers
        if is_down and not was_down:
            self._held_modifiers[keycode] = name
            self._dispatch(KeyEvent(name, KEY_DOWN, None))
        elif was_down and not is_down:
            self._held_modifiers.pop(keycode, None)
            self._dispatch(KeyEvent(name, KEY_UP, None))

    def _physical_key_is_down(self, keycode: int) -> bool | None:
        """Read one physical key's state without using aggregate modifier flags."""
        quartz = self._quartz
        state_query = getattr(quartz, "CGEventSourceKeyState", None)
        state_id = getattr(quartz, "kCGEventSourceStateHIDSystemState", None)
        if state_query is None or state_id is None:
            return None
        try:
            return bool(state_query(state_id, keycode))
        except Exception:
            return None

    def _sync_held_modifiers(self) -> None:
        """Release tracked modifiers whose physical key is no longer down."""
        releases: list[KeyEvent] = []
        with self._lock:
            for keycode, name in tuple(self._held_modifiers.items()):
                if self._physical_key_is_down(keycode) is False:
                    self._held_modifiers.pop(keycode, None)
                    releases.append(KeyEvent(name, KEY_UP, None))
        for event in releases:
            self._dispatch(event)

    def _release_held_keys(self) -> None:
        with self._lock:
            releases = [KeyEvent(name, KEY_UP, None) for name in self._held_keys]
            self._held_keys.clear()
            self._held_modifiers.clear()
        for event in releases:
            self._dispatch(event)

    def unhook(self, token: object) -> None:
        with self._lock:
            self._tokens.pop(token, None)
            stop = not self._tokens
            if stop:
                self._held_keys.clear()
                self._held_modifiers.clear()
        if stop:
            self._stop_tap()

    def unhook_all(self) -> None:
        self._release_held_keys()
        with self._lock:
            self._tokens.clear()
        self._stop_tap()

    def _stop_tap(self) -> None:
        thread = self._thread
        if thread is None:
            return
        quartz, core_foundation, _ = self._load_native()
        if self._stop_requested is not None:
            self._stop_requested.set()
        if self._tap is not None:
            quartz.CGEventTapEnable(self._tap, False)
        if self._run_loop is not None:
            core_foundation.CFRunLoopStop(self._run_loop)
            core_foundation.CFRunLoopWakeUp(self._run_loop)
        if thread is not threading.current_thread():
            thread.join(timeout=5)
        if not thread.is_alive():
            self._thread = self._ready = self._stop_requested = None
            self._run_loop = None

    def simulate_keys(
        self, key: str, modifier_keys: Iterable[str] | None = None, target: int | None = None
    ) -> None:
        with self._simulation_lock:
            self._simulate_keys(key, modifier_keys, target)

    def _simulate_keys(
        self, key: str, modifier_keys: Iterable[str] | None = None, target: int | None = None
    ) -> None:
        quartz, _, appkit = self._load_native()
        self._check_permission(quartz, "post")
        key = normalize_key(key)
        keycode = _MAC_POST_KEYCODES.get(key)
        if keycode is None:
            raise PlatformInputError(f"Unsupported macOS key: {key!r}")
        modifiers = []
        for modifier in modifier_keys or ():
            normalized = normalize_key(modifier)
            code = _MAC_POST_KEYCODES.get(normalized)
            if code is not None and code != keycode:
                modifiers.append(code)
        app = None
        if target:
            app = appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_(int(target))
            if app is None or not app.activateWithOptions_(
                appkit.NSApplicationActivateIgnoringOtherApps
            ):
                raise PlatformInputError(f"Could not activate target application process {target}.")
        source = quartz.CGEventSourceCreate(quartz.kCGEventSourceStatePrivate)
        if source is None:
            raise PlatformInputError("Could not create a private macOS keyboard event source.")
        self._simulating = True
        pressed: list[int] = []
        active_flags = 0
        try:
            for code in [*modifiers, keycode]:
                active_flags |= self._modifier_flag(quartz, code)
                self._post_key(quartz, source, code, True, target, active_flags)
                pressed.append(code)
            active_flags = self._modifier_flags(quartz, pressed[:-1])
            self._post_key(quartz, source, keycode, False, target, active_flags)
            pressed.pop()
            for code in reversed(modifiers):
                active_flags = self._modifier_flags(quartz, pressed[:-1])
                self._post_key(quartz, source, code, False, target, active_flags)
                pressed.pop()
        except Exception:
            for code in reversed(pressed):
                try:
                    active_flags = self._modifier_flags(quartz, pressed[:-1])
                    self._post_key(quartz, source, code, False, target, active_flags)
                except Exception:
                    pass
                pressed.pop()
            raise
        finally:
            self._simulating = False

    def _post_key(
        self, quartz: Any, source: Any, keycode: int, down: bool, target: int | None, flags: int
    ) -> None:
        event = quartz.CGEventCreateKeyboardEvent(source, keycode, down)
        if event is None:
            raise PlatformInputError("Could not create a macOS keyboard event.")
        quartz.CGEventSetIntegerValueField(
            event, quartz.kCGEventSourceUserData, self._SYNTHETIC_MARKER
        )
        quartz.CGEventSetFlags(event, flags)
        if target:
            post_to_pid = getattr(quartz, "CGEventPostToPid", None)
            if post_to_pid is None:
                raise PlatformInputError(
                    "This PyObjC Quartz version does not support targeted event posting."
                )
            post_to_pid(int(target), event)
        else:
            quartz.CGEventPost(quartz.kCGHIDEventTap, event)

    @staticmethod
    def _modifier_flag(quartz: Any, keycode: int) -> int:
        modifier = _MAC_MODIFIERS.get(keycode)
        if modifier is None:
            return 0
        return int(getattr(quartz, modifier[1], 0))

    def _modifier_flags(self, quartz: Any, keycodes: Iterable[int]) -> int:
        flags = 0
        for keycode in keycodes:
            flags |= self._modifier_flag(quartz, keycode)
        return flags

    def foreground_target(self, own_window_ids: Iterable[int] = ()) -> int | None:
        _, _, appkit = self._load_native()
        app = appkit.NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return None
        pid = int(app.processIdentifier())
        current = appkit.NSRunningApplication.currentApplication()
        own_pid = int(current.processIdentifier()) if current is not None else -1
        if pid <= 0 or pid == own_pid or pid in set(own_window_ids):
            return None
        return pid
