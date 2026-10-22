import sys
import threading
from types import SimpleNamespace

import pytest

import platform_input as input_api


def test_windows_legacy_normalization_preserves_scan_code_precedence():
    assert input_api.normalize_key("right shift", 42) == "shift"
    assert input_api.normalize_key("A") == "a"
    assert input_api.normalize_key("?") == "/"
    assert input_api.normalize_key("caps lock") == "caps"
    assert input_api.normalize_key("", 0) == ""


def test_mac_ansi_keycode_zero_and_modifier_names_are_not_scan_codes():
    assert input_api._MAC_KEYCODES[0] == "a"
    assert input_api.normalize_key("a", None) == "a"
    assert input_api.normalize_key("cmd", None) == "win"
    assert input_api.normalize_key("command", None) == "win"
    assert input_api.normalize_key("option", None) == "alt"
    assert input_api._WINDOWS_VK_MAP["a"] == 0x41
    assert input_api._WINDOWS_VK_MAP["z"] == 0x5A
    assert input_api._MAC_POST_KEYCODES["1"] == 18
    assert input_api._MAC_POST_KEYCODES["a"] == 0
    assert input_api._MAC_POST_KEYCODES["win"] == 55
    assert input_api._MAC_POST_KEYCODES["rwin"] == 54
    assert input_api._MAC_KEYCODES[55] == "cmd"
    assert input_api._MAC_KEYCODES[58] == "alt"


def test_create_backend_selects_platform_lazily(monkeypatch):
    monkeypatch.setattr(input_api.sys, "platform", "darwin")
    backend = input_api.create_backend()
    assert isinstance(backend, input_api.MacOSBackend)
    assert backend._thread is None
    assert backend._quartz is None

    monkeypatch.setattr(input_api.sys, "platform", "win32")
    assert isinstance(input_api.create_backend(), input_api.WindowsBackend)


def _modifier_backend():
    backend = input_api.MacOSBackend()
    physical = {56: False, 60: False}
    backend._quartz = SimpleNamespace(
        kCGEventFlagMaskShift=1,
        kCGEventFlagMaskControl=2,
        kCGEventSourceStateHIDSystemState=99,
        CGEventSourceKeyState=lambda state, keycode: physical.get(keycode, False),
        CGEventGetFlags=lambda event: event.flags,
    )
    events = []
    backend._tokens[object()] = events.append
    backend._stop_tap = lambda: None
    return backend, physical, events


def test_mac_flags_changed_tracks_both_modifier_sides_and_release_cleanup():
    backend, physical, events = _modifier_backend()
    left_shift = SimpleNamespace(flags=1)
    right_shift = SimpleNamespace(flags=1)
    released_shift = SimpleNamespace(flags=1)

    physical[56] = True
    backend._dispatch_modifier(56, left_shift)
    physical[60] = True
    backend._dispatch_modifier(60, right_shift)
    physical[56] = False
    backend._dispatch_modifier(56, released_shift)
    assert [(event.name, event.event_type) for event in events] == [
        ("shift", "down"),
        ("rshift", "down"),
        ("shift", "up"),
    ]
    assert backend._held_modifiers == {60: "rshift"}

    backend.unhook_all()
    assert events[-1] == input_api.KeyEvent("rshift", input_api.KEY_UP, None)
    assert backend._held_modifiers == {}


def test_mac_releasing_left_shift_held_before_listening_does_not_create_a_press():
    backend, physical, events = _modifier_backend()
    physical.update({56: True, 60: True})

    # Both physical keys were down before the tap observed either transition.
    physical[56] = False
    backend._dispatch_modifier(56, SimpleNamespace(flags=1))
    assert backend._held_modifiers == {}
    assert events == []

    physical[60] = False
    backend._dispatch_modifier(60, SimpleNamespace(flags=0))
    assert backend._held_modifiers == {}
    assert events == []


def test_mac_missed_modifier_release_is_reconciled_before_later_press():
    backend, physical, events = _modifier_backend()
    physical[56] = True
    backend._dispatch_modifier(56, SimpleNamespace(flags=1))

    # Model a later ordinary hardware event after the modifier's release event
    # was dropped by Quartz; reconciliation queries tracked keys only.
    physical[56] = False
    backend._sync_held_modifiers()
    assert events == [
        input_api.KeyEvent("shift", input_api.KEY_DOWN, None),
        input_api.KeyEvent("shift", input_api.KEY_UP, None),
    ]
    assert backend._held_modifiers == {}

    physical[56] = True
    backend._dispatch_modifier(56, SimpleNamespace(flags=1))
    assert events[-1] == input_api.KeyEvent("shift", input_api.KEY_DOWN, None)
    assert backend._held_modifiers == {56: "shift"}


def test_mac_event_tap_ignores_private_synthetic_marker():
    backend = input_api.MacOSBackend()
    backend._quartz = SimpleNamespace(
        kCGEventKeyDown=10,
        kCGEventKeyUp=11,
        kCGEventFlagsChanged=12,
        kCGEventTapDisabledByTimeout=13,
        kCGEventTapDisabledByUserInput=14,
        kCGEventSourceUserData=20,
        kCGKeyboardEventKeycode=21,
        kCGSessionEventTap=1,
        kCGHeadInsertEventTap=2,
        kCGEventTapOptionListenOnly=3,
        CGEventTapEnable=lambda *_: None,
        CGEventGetIntegerValueField=lambda event, field: event.values[field],
    )
    seen = []
    backend._tokens[object()] = seen.append
    native = backend._quartz
    native.CGEventTapEnable = lambda *_: None
    core = SimpleNamespace(
        CFMachPortCreateRunLoopSource=lambda *_: "source",
        CFRunLoopGetCurrent=lambda: "loop",
        CFRunLoopAddSource=lambda *_: None,
        kCFRunLoopDefaultMode="default",
        CFRunLoopRun=lambda: None,
        CFRunLoopRemoveSource=lambda *_: None,
        CFMachPortInvalidate=lambda *_: None,
    )

    def create_tap(location, placement, options, mask, callback, user_info):
        synthetic = SimpleNamespace(values={20: backend._SYNTHETIC_MARKER, 21: 0})
        hardware = SimpleNamespace(values={20: 0, 21: 0})
        callback(None, 10, synthetic, None)
        callback(None, 10, hardware, None)
        return object()

    native.CGEventTapCreate = create_tap
    backend._core_foundation = core
    backend._ready = threading.Event()
    backend._stop_requested = threading.Event()
    backend._tap_thread_main()
    assert seen == [input_api.KeyEvent("a", input_api.KEY_DOWN)]


def test_mac_disabled_tap_releases_held_modifiers_and_later_press_works():
    backend = input_api.MacOSBackend()
    physical = {56: False}
    callbacks = {}
    enabled = []
    native = SimpleNamespace(
        kCGEventKeyDown=10,
        kCGEventKeyUp=11,
        kCGEventFlagsChanged=12,
        kCGEventTapDisabledByTimeout=13,
        kCGEventTapDisabledByUserInput=14,
        kCGEventSourceUserData=20,
        kCGKeyboardEventKeycode=21,
        kCGEventSourceStateHIDSystemState=99,
        kCGEventFlagMaskShift=1,
        kCGSessionEventTap=1,
        kCGHeadInsertEventTap=2,
        kCGEventTapOptionListenOnly=3,
        CGEventTapEnable=lambda tap, value: enabled.append(value),
        CGEventSourceKeyState=lambda state, keycode: physical.get(keycode, False),
        CGEventGetFlags=lambda event: event.get("flags", 0),
        CGEventGetIntegerValueField=lambda event, field: event.get(field, 0),
    )
    backend._quartz = native
    events = []
    backend._tokens[object()] = events.append

    def create_tap(location, placement, options, mask, callback, user_info):
        callbacks["tap"] = callback
        return object()

    def run_loop():
        callback = callbacks["tap"]
        physical[56] = True
        callback(None, 12, {20: 0, 21: 56, "flags": 1}, None)
        physical[56] = False
        callback(None, 13, {}, None)
        physical[56] = True
        callback(None, 12, {20: 0, 21: 56, "flags": 1}, None)

    native.CGEventTapCreate = create_tap
    backend._core_foundation = SimpleNamespace(
        CFMachPortCreateRunLoopSource=lambda *_: "source",
        CFRunLoopGetCurrent=lambda: "loop",
        CFRunLoopAddSource=lambda *_: None,
        kCFRunLoopDefaultMode="default",
        CFRunLoopRun=run_loop,
        CFRunLoopRemoveSource=lambda *_: None,
        CFMachPortInvalidate=lambda *_: None,
    )
    backend._ready = threading.Event()
    backend._stop_requested = threading.Event()
    backend._tap_thread_main()

    assert events == [
        input_api.KeyEvent("shift", input_api.KEY_DOWN, None),
        input_api.KeyEvent("shift", input_api.KEY_UP, None),
        input_api.KeyEvent("shift", input_api.KEY_DOWN, None),
    ]
    assert enabled == [True, True]
    assert backend._held_modifiers == {56: "shift"}


def test_mac_disabled_tap_releases_ordinary_key_and_later_press_works():
    backend = input_api.MacOSBackend()
    callbacks = {}
    native = SimpleNamespace(
        kCGEventKeyDown=10,
        kCGEventKeyUp=11,
        kCGEventFlagsChanged=12,
        kCGEventTapDisabledByTimeout=13,
        kCGEventTapDisabledByUserInput=14,
        kCGEventSourceUserData=20,
        kCGKeyboardEventKeycode=21,
        kCGSessionEventTap=1,
        kCGHeadInsertEventTap=2,
        kCGEventTapOptionListenOnly=3,
        CGEventTapEnable=lambda *_: None,
        CGEventGetIntegerValueField=lambda event, field: event.get(field, 0),
    )
    backend._quartz = native
    events = []
    backend._tokens[object()] = events.append

    def create_tap(location, placement, options, mask, callback, user_info):
        callbacks["tap"] = callback
        return object()

    def run_loop():
        callback = callbacks["tap"]
        callback(None, 10, {20: 0, 21: 49}, None)
        callback(None, 13, {}, None)
        callback(None, 10, {20: 0, 21: 49}, None)

    native.CGEventTapCreate = create_tap
    backend._core_foundation = SimpleNamespace(
        CFMachPortCreateRunLoopSource=lambda *_: "source",
        CFRunLoopGetCurrent=lambda: "loop",
        CFRunLoopAddSource=lambda *_: None,
        kCFRunLoopDefaultMode="default",
        CFRunLoopRun=run_loop,
        CFRunLoopRemoveSource=lambda *_: None,
        CFMachPortInvalidate=lambda *_: None,
    )
    backend._ready = threading.Event()
    backend._stop_requested = threading.Event()
    backend._tap_thread_main()

    assert events == [
        input_api.KeyEvent("space", input_api.KEY_DOWN, None),
        input_api.KeyEvent("space", input_api.KEY_UP, None),
        input_api.KeyEvent("space", input_api.KEY_DOWN, None),
    ]
    assert backend._held_keys == {"space"}


def test_mac_unhook_all_releases_ordinary_keys_before_removing_callbacks():
    backend = input_api.MacOSBackend()
    events = []
    backend._tokens[object()] = events.append
    backend._dispatch(input_api.KeyEvent("space", input_api.KEY_DOWN, None))

    backend.unhook_all()

    assert events == [
        input_api.KeyEvent("space", input_api.KEY_DOWN, None),
        input_api.KeyEvent("space", input_api.KEY_UP, None),
    ]
    assert backend._held_keys == set()
    assert backend._tokens == {}


def test_mac_permission_failure_is_clear_and_does_not_start_tap():
    backend = input_api.MacOSBackend()
    backend._quartz = SimpleNamespace(CGPreflightListenEventAccess=lambda: False)
    with pytest.raises(input_api.InputPermissionError, match="Input Monitoring"):
        backend._check_permission(backend._quartz, "listen")
    assert backend._thread is None


def test_mac_foreground_pid_excludes_own_window_ids():
    app = SimpleNamespace(processIdentifier=lambda: 4321)
    current = SimpleNamespace(processIdentifier=lambda: 1)
    workspace = SimpleNamespace(frontmostApplication=lambda: app)
    backend = input_api.MacOSBackend()
    backend._quartz = SimpleNamespace()
    backend._core_foundation = SimpleNamespace()
    backend._appkit = SimpleNamespace(
        NSWorkspace=SimpleNamespace(sharedWorkspace=lambda: workspace),
        NSRunningApplication=SimpleNamespace(currentApplication=lambda: current),
    )
    assert backend.foreground_target() == 4321
    assert backend.foreground_target((4321,)) is None


def test_windows_hooks_use_tokens_and_map_events(monkeypatch):
    calls = {}

    def hook(callback):
        calls["hook"] = callback
        return "hook-handle"

    keyboard = SimpleNamespace(
        hook=hook,
        on_press=lambda callback: "press-handle",
        unhook=lambda handle: calls.setdefault("unhooked", []).append(handle),
    )
    monkeypatch.setitem(sys.modules, "keyboard", keyboard)
    backend = input_api.WindowsBackend()
    events = []
    token = backend.hook(events.append)
    calls["hook"](SimpleNamespace(name="A", event_type="down", scan_code=30))
    assert events == [input_api.KeyEvent("a", input_api.KEY_DOWN, 30)]
    backend.unhook(token)
    assert calls["unhooked"] == ["hook-handle"]


def test_mac_caps_lock_flags_change_emits_press_and_release():
    backend = input_api.MacOSBackend()
    events = []
    backend._tokens[object()] = events.append
    backend._dispatch_modifier(57, SimpleNamespace())
    assert events == [
        input_api.KeyEvent("caps", input_api.KEY_DOWN, None),
        input_api.KeyEvent("caps", input_api.KEY_UP, None),
    ]


def test_mac_removing_last_hook_clears_modifier_state():
    backend = input_api.MacOSBackend()
    token = object()
    backend._tokens[token] = lambda event: None
    backend._held_modifiers[56] = "shift"
    backend.unhook(token)
    assert not backend._held_modifiers
    assert not backend._tokens


def test_mac_simulation_uses_ansi_a_and_sets_command_flags():
    posted = []
    quartz = SimpleNamespace(
        CGPreflightPostEventAccess=lambda: True,
        kCGEventSourceStatePrivate=1,
        kCGEventSourceUserData=2,
        kCGEventFlagMaskCommand=4,
        kCGEventFlagMaskShift=1,
        kCGEventFlagMaskAlternate=2,
        kCGEventFlagMaskControl=8,
        kCGEventFlagMaskAlphaShift=16,
        kCGHIDEventTap=3,
        CGEventSourceCreate=lambda _: object(),
        CGEventCreateKeyboardEvent=lambda source, code, down: {"keycode": code, "down": down},
        CGEventSetIntegerValueField=lambda event, field, value: event.update({"marker": value}),
        CGEventSetFlags=lambda event, value: event.update({"flags": value}),
        CGEventPost=lambda tap, event: posted.append(event.copy()),
    )
    backend = input_api.MacOSBackend()
    backend._quartz = quartz
    backend._core_foundation = SimpleNamespace()
    backend._appkit = SimpleNamespace()
    backend.simulate_keys("a", ["command"])
    assert [event["keycode"] for event in posted] == [55, 0, 0, 55]
    assert posted[1]["flags"] == quartz.kCGEventFlagMaskCommand
    assert all(event["marker"] == backend._SYNTHETIC_MARKER for event in posted)
    assert backend.is_simulating is False
    posted.clear()
    backend.simulate_keys("rshift", ["shift"])
    assert [event["keycode"] for event in posted] == [56, 60, 60, 56]
    assert [event["flags"] for event in posted] == [1, 1, 1, 0]


@pytest.mark.skipif(sys.platform != "darwin", reason="requires macOS Quartz PyObjC")
def test_real_quartz_event_wrapper_api_roundtrip_without_posting():
    import Quartz

    event = Quartz.CGEventCreateKeyboardEvent(None, 0, True)
    assert event is not None
    marker = 0x534B4244
    Quartz.CGEventSetIntegerValueField(event, Quartz.kCGEventSourceUserData, marker)
    assert Quartz.CGEventGetIntegerValueField(event, Quartz.kCGEventSourceUserData) == marker
