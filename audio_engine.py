"""Audio loading and transformations for SoundKeyboard."""

import json
import os
import sys
import time

import numpy as np
import pygame
import pygame.sndarray
from PyQt5.QtCore import QTimer


def get_default_pack_path():
    """Return the pack directory beside the source file or frozen executable."""
    if getattr(sys, "frozen", False):
        app_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        app_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(app_dir, "default_pack")


def make_reversed_sound(filepath):
    try:
        snd = pygame.mixer.Sound(filepath)
        data = pygame.sndarray.array(snd)
        return pygame.sndarray.make_sound(data[::-1].copy())
    except Exception:
        return None


def make_octave_down_sound(filepath):
    try:
        snd = pygame.mixer.Sound(filepath)
        data = pygame.sndarray.array(snd)
        framerate = 44100
        grain_size = int(framerate * 0.05)
        if grain_size < 2 or len(data) == 0:
            return snd

        n = data.shape[0]
        out = np.zeros_like(data)

        for i in range(0, n, grain_size):
            grain = data[i : i + grain_size]
            g_len = len(grain)
            if g_len < 2:
                out[i : i + g_len] = grain
                continue

            x = np.arange(g_len)
            xn = np.linspace(0, g_len - 1, g_len * 2)
            if data.ndim == 1:
                stretched = np.interp(xn, x, grain).astype(data.dtype)
                out[i : i + g_len] = stretched[:g_len]
            else:
                stretched = np.zeros((g_len * 2, data.shape[1]), dtype=data.dtype)
                for channel in range(data.shape[1]):
                    stretched[:, channel] = np.interp(xn, x, grain[:, channel]).astype(data.dtype)
                out[i : i + g_len] = stretched[:g_len]

        return pygame.sndarray.make_sound(out)
    except Exception:
        return None


class AudioEngine:
    def __init__(self, pack_dir=None):
        pygame.mixer.pre_init(44100, -16, 2, 512)
        pygame.init()
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        pygame.mixer.set_num_channels(32)
        self.sounds_normal = {}
        self.sounds_reversed = {}
        self.sounds_octdown = {}
        self.sounds_rev_oct = {}
        self.rules = {}
        self.pack_dir = ""
        self.is_performance_mode = False
        self.performance_sounds = {}
        self.space_channel = None
        self.shift_reverse = False
        self.caps_octave_down = False
        self.space_playing = False
        self.space_start_time = 0.0
        self.current_space_snd = None
        self.load_pack(pack_dir or get_default_pack_path())

    def load_pack(self, pack_dir, overwrite_rules=True):
        self.pack_dir = pack_dir
        rule_path = os.path.join(pack_dir, "rule.json")
        if overwrite_rules:
            if not os.path.exists(rule_path):
                self.rules = {"space": {"file": "", "enabled": True}}
                self.save_rules()
            else:
                try:
                    with open(rule_path, encoding="utf-8") as stream:
                        self.rules = json.load(stream)
                except (OSError, json.JSONDecodeError):
                    pass
        else:
            self.save_rules()
        self.reload_sounds()

    def reload_sounds(self):
        self.sounds_normal.clear()
        self.sounds_reversed.clear()
        self.sounds_octdown.clear()
        self.sounds_rev_oct.clear()
        for key, cfg in self.rules.items():
            if cfg.get("enabled", True) and cfg.get("file"):
                filepath = cfg["file"]
                if not os.path.isabs(filepath) and self.pack_dir:
                    filepath = os.path.join(self.pack_dir, filepath)
                if not os.path.exists(filepath):
                    continue
                normalized_key = key.lower()
                try:
                    self.sounds_normal[normalized_key] = pygame.mixer.Sound(filepath)
                    reversed_sound = make_reversed_sound(filepath)
                    if reversed_sound:
                        self.sounds_reversed[normalized_key] = reversed_sound
                    octave_down = make_octave_down_sound(filepath)
                    if octave_down:
                        self.sounds_octdown[normalized_key] = octave_down
                        reverse_octave = pygame.sndarray.array(octave_down)[::-1].copy()
                        self.sounds_rev_oct[normalized_key] = pygame.sndarray.make_sound(
                            reverse_octave
                        )
                except Exception as exc:
                    print(f"音效加载失败[{normalized_key}]: {exc}")

    def save_rules(self):
        if not self.pack_dir:
            self.pack_dir = get_default_pack_path()
        os.makedirs(self.pack_dir, exist_ok=True)
        try:
            with open(os.path.join(self.pack_dir, "rule.json"), "w", encoding="utf-8") as stream:
                json.dump(self.rules, stream, indent=4, ensure_ascii=False)
        except OSError as exc:
            print(f"Error saving rules: {exc}")

    def _get_sound(self, key):
        if self.shift_reverse and self.caps_octave_down:
            return self.sounds_rev_oct.get(key)
        if self.shift_reverse:
            return self.sounds_reversed.get(key)
        if self.caps_octave_down:
            return self.sounds_octdown.get(key)
        return self.sounds_normal.get(key)

    def toggle_caps(self):
        self.caps_octave_down = not self.caps_octave_down

    def toggle_shift(self):
        self.shift_reverse = not self.shift_reverse

    def _delayed_space_pause(self):
        if not self.space_playing and self.space_channel:
            self.space_channel.pause()

    def play_key(self, key):
        if key == "caps":
            self.toggle_caps()
            return
        if key in ("shift", "rshift"):
            self.toggle_shift()
            return
        if self.is_performance_mode:
            if key in self.performance_sounds:
                self.performance_sounds[key].play()
            return
        cfg = self.rules.get(key, {})
        if not cfg.get("enabled", True):
            return
        sound = self._get_sound(key)
        if not sound:
            return
        if key == "space":
            self.space_playing = True
            self.space_start_time = time.time()
            if self.space_channel and self.current_space_snd == sound:
                self.space_channel.unpause()
                if not self.space_channel.get_busy():
                    self.space_channel.play(sound)
            else:
                self.space_channel = pygame.mixer.find_channel(True)
                if self.space_channel:
                    self.space_channel.play(sound)
                self.current_space_snd = sound
        else:
            channel = pygame.mixer.find_channel(True)
            if channel:
                channel.play(sound)

    def release_key(self, key):
        if key == "space" and self.space_playing:
            self.space_playing = False
            elapsed = time.time() - self.space_start_time
            if elapsed < 0.3:
                QTimer.singleShot(int((0.3 - elapsed) * 1000), self._delayed_space_pause)
            elif self.space_channel:
                self.space_channel.pause()

    def load_performance_key(self, filepath):
        try:
            sound = pygame.mixer.Sound(filepath)
            data = pygame.sndarray.array(sound)
            key_semitones = {"a": 0, "s": 2, "d": 4, "f": 5, "g": 7, "h": 9, "j": 11, "k": 12}
            self.performance_sounds.clear()
            sample_count = data.shape[0]

            for key, semitones in key_semitones.items():
                if semitones == 0:
                    self.performance_sounds[key] = pygame.mixer.Sound(filepath)
                    continue
                factor = 2 ** (semitones / 12.0)
                new_count = int(sample_count / factor)
                x = np.arange(new_count) * factor
                if data.ndim == 1:
                    resampled = np.interp(x, np.arange(sample_count), data).astype(data.dtype)
                else:
                    resampled = np.zeros((new_count, data.shape[1]), dtype=data.dtype)
                    for channel in range(data.shape[1]):
                        resampled[:, channel] = np.interp(
                            x, np.arange(sample_count), data[:, channel]
                        ).astype(data.dtype)
                self.performance_sounds[key] = pygame.sndarray.make_sound(resampled)
            self.is_performance_mode = True
        except (OSError, pygame.error, ValueError) as exc:
            print(f"演奏模式失败: {exc}")
