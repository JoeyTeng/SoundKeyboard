import audio_engine


def test_macos_frozen_pack_path_uses_application_support(monkeypatch, tmp_path):
    monkeypatch.setattr(audio_engine.sys, "platform", "darwin")
    monkeypatch.setattr(audio_engine.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        audio_engine.os.path,
        "expanduser",
        lambda path: str(tmp_path / path[2:]),
    )

    assert audio_engine.get_default_pack_path() == str(
        tmp_path / "Library/Application Support/SoundKeyboard/default_pack"
    )
