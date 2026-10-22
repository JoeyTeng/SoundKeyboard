import json
import wave

import numpy as np
import pygame
import pytest

from audio_engine import AudioEngine, get_default_pack_path


@pytest.fixture
def engine(tmp_path):
    audio_engine = AudioEngine(pack_dir=str(tmp_path))
    try:
        yield audio_engine
    finally:
        pygame.mixer.quit()


def write_wave(path, samples, sample_rate=44100):
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(samples.shape[1] if samples.ndim == 2 else 1)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        stream.writeframes(samples.astype(np.int16).tobytes())


def test_reversed_audio_and_octave_variants_load_from_pack(engine, tmp_path):
    samples = np.column_stack(
        (np.arange(4096, dtype=np.int16), np.arange(4096, dtype=np.int16) * 2)
    )
    write_wave(tmp_path / "asymmetric.wav", samples)
    engine.rules = {"a": {"file": "asymmetric.wav", "enabled": True}}
    engine.save_rules()
    engine.load_pack(str(tmp_path))

    np.testing.assert_array_equal(pygame.sndarray.array(engine.sounds_normal["a"]), samples)
    np.testing.assert_array_equal(pygame.sndarray.array(engine.sounds_reversed["a"]), samples[::-1])
    assert "a" in engine.sounds_octdown
    np.testing.assert_array_equal(
        pygame.sndarray.array(engine.sounds_rev_oct["a"]),
        pygame.sndarray.array(engine.sounds_octdown["a"])[::-1],
    )


def test_performance_mode_builds_pitch_variants(engine, tmp_path):
    samples = np.column_stack(
        (np.arange(4410, dtype=np.int16), np.arange(4410, dtype=np.int16) * 2)
    )
    source = tmp_path / "pitch.wav"
    write_wave(source, samples)

    engine.load_performance_key(str(source))

    assert engine.is_performance_mode
    assert set(engine.performance_sounds) == set("asdfghjk")
    assert len(pygame.sndarray.array(engine.performance_sounds["a"])) == len(samples)
    assert len(pygame.sndarray.array(engine.performance_sounds["k"])) < len(samples)


def test_rules_round_trip_and_save_creates_pack(engine, tmp_path):
    engine.rules = {"space": {"file": "", "enabled": True}, "a": {"file": "a.wav"}}
    engine.save_rules()
    saved = json.loads((tmp_path / "rule.json").read_text(encoding="utf-8"))
    assert saved == engine.rules

    engine.rules = {}
    engine.load_pack(str(tmp_path))
    assert engine.rules == saved


def test_source_default_pack_is_next_to_audio_module(monkeypatch, tmp_path):
    monkeypatch.delattr("audio_engine.sys.frozen", raising=False)
    module_dir = tmp_path / "source"
    module_dir.mkdir()
    monkeypatch.setattr("audio_engine.__file__", str(module_dir / "audio_engine.py"))
    expected = str(module_dir / "default_pack")

    assert get_default_pack_path() == expected


def test_invalid_utf8_rules_do_not_prevent_startup(tmp_path):
    (tmp_path / "rule.json").write_bytes(b"\xff\xfeinvalid rules")
    engine = AudioEngine(pack_dir=str(tmp_path))
    try:
        assert engine.rules == {}
    finally:
        pygame.mixer.quit()


def test_frozen_default_pack_is_next_to_executable(monkeypatch, tmp_path):
    monkeypatch.setattr("audio_engine.sys.frozen", True, raising=False)
    monkeypatch.setattr("audio_engine.sys.executable", str(tmp_path / "SoundKeyboard.exe"))

    assert get_default_pack_path() == str(tmp_path / "default_pack")
