from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "publish_preview.py"
SPEC = importlib.util.spec_from_file_location("publish_preview", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)

SHA = "a" * 40
RUN_ID = "123456789"
ENV = {
    "GITHUB_REPOSITORY": "JoeyTeng/SoundKeyboard",
    "GITHUB_SHA": SHA,
    "GITHUB_REF": "refs/heads/main",
    "GITHUB_EVENT_NAME": "push",
    "GITHUB_RUN_ID": RUN_ID,
}


def make_assets(directory: Path) -> Path:
    directory.mkdir()
    for index, name in enumerate(publisher.EXPECTED_ASSETS, start=1):
        (directory / name).write_bytes(f"binary-{index}".encode())
    return directory


def api_response(
    status: int, body: dict[str, Any] | None = None
) -> subprocess.CompletedProcess[str]:
    payload = json.dumps(body or {})
    output = f"HTTP/2.0 {status} OK\r\ncontent-type: application/json\r\n\r\n{payload}"
    return subprocess.CompletedProcess(["gh"], 0 if status < 400 else 1, output, "")


def test_full_success_creates_uploads_and_publishes_exact_commit(tmp_path, monkeypatch):
    assets = make_assets(tmp_path / "release-assets")
    calls: list[list[str]] = []
    tag = f"preview-{SHA}"

    def api(endpoint: str):
        if endpoint.endswith("/commits/main"):
            return {"sha": SHA}
        assert endpoint.endswith(f"/releases/tags/{tag}") or endpoint.endswith(
            f"/git/ref/tags/{tag}"
        )
        return None

    def gh(args: list[str], **kwargs):
        calls.append(args)
        if args[:2] == ["release", "create"]:
            assert args[2] == tag
            assert args[3:5] == ["--draft", "--prerelease"]
            assert args[args.index("--target") + 1] == SHA
            assert args[-2:] == ["--repo", publisher.REPOSITORY]
            notes = Path(args[args.index("--notes-file") + 1]).read_text()
            assert f"Source commit: `{SHA}`" in notes
            assert f"actions/runs/{RUN_ID}" in notes
        elif args[:2] == ["release", "upload"]:
            assert args[2] == tag and args[-3:] == ["--clobber", "--repo", publisher.REPOSITORY]
            uploaded = [Path(item) for item in args[3:-3]]
            assert {path.name for path in uploaded} == set(publisher.EXPECTED_RELEASE_ASSETS)
            sums = (Path(args[3]).parent / "SHA256SUMS.txt").read_text().splitlines()
            actual_hashes = {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in uploaded
                if path.name != "SHA256SUMS.txt"
            }
            listed_hashes = {
                filename: digest for digest, filename in (line.split("  ", 1) for line in sums)
            }
            assert listed_hashes == actual_hashes
        return subprocess.CompletedProcess(["gh", *args], 0, "", "")

    monkeypatch.setattr(publisher, "_api_get", api)
    monkeypatch.setattr(publisher, "_api_get_json", lambda endpoint: [])
    monkeypatch.setattr(publisher, "_run_gh", gh)

    assert publisher.publish(assets, ENV) == f"Published preview release {tag}."
    assert [call[:2] for call in calls] == [
        ["release", "create"],
        ["release", "upload"],
        ["release", "edit"],
    ]
    assert calls[-1] == [
        "release",
        "edit",
        tag,
        "--draft=false",
        "--latest=false",
        "--repo",
        publisher.REPOSITORY,
    ]


def test_upload_failure_does_not_publish_draft(tmp_path, monkeypatch):
    assets = make_assets(tmp_path / "release-assets")
    tag = f"preview-{SHA}"

    def api(endpoint: str):
        if endpoint.endswith("/commits/main"):
            return {"sha": SHA}
        assert endpoint.endswith(f"/releases/tags/{tag}") or endpoint.endswith(
            f"/git/ref/tags/{tag}"
        )
        return None

    calls: list[list[str]] = []

    def gh(args: list[str], **kwargs):
        calls.append(args)
        if args[:2] == ["release", "upload"]:
            return subprocess.CompletedProcess(["gh", *args], 1, "", "upload failed")
        return subprocess.CompletedProcess(["gh", *args], 0, "", "")

    monkeypatch.setattr(publisher, "_api_get", api)
    monkeypatch.setattr(publisher, "_api_get_json", lambda endpoint: [])
    monkeypatch.setattr(publisher, "_run_gh", gh)

    with pytest.raises(publisher.PublishError, match="Could not upload"):
        publisher.publish(assets, ENV)

    assert [call[:2] for call in calls] == [["release", "create"], ["release", "upload"]]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("GITHUB_EVENT_NAME", "pull_request"),
        ("GITHUB_REF", "refs/heads/feature"),
        ("GITHUB_REPOSITORY", "someone/else"),
    ],
)
def test_wrong_context_is_rejected_before_api_or_writes(tmp_path, monkeypatch, key, value):
    calls = []
    monkeypatch.setattr(publisher, "_api_get", lambda endpoint: calls.append(endpoint))
    monkeypatch.setattr(publisher, "_run_gh", lambda args: calls.append(args))
    env = {**ENV, key: value}

    with pytest.raises(publisher.PublishError):
        publisher.publish(tmp_path / "does-not-exist", env)

    assert calls == []


def test_stale_main_commit_skips_without_validating_assets_or_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(publisher, "_api_get", lambda endpoint: {"sha": "b" * 40})
    writes = []
    monkeypatch.setattr(publisher, "_run_gh", lambda args: writes.append(args))

    assert "skipped" in publisher.publish(tmp_path / "does-not-exist", ENV)
    assert writes == []


@pytest.mark.parametrize("empty", [False, True])
def test_missing_or_empty_binary_fails_before_release_writes(tmp_path, monkeypatch, empty):
    assets = make_assets(tmp_path / "release-assets")
    if empty:
        (assets / publisher.EXPECTED_ASSETS[0]).write_bytes(b"")
    else:
        (assets / publisher.EXPECTED_ASSETS[0]).unlink()
    monkeypatch.setattr(publisher, "_api_get", lambda endpoint: {"sha": SHA})
    writes = []
    monkeypatch.setattr(publisher, "_run_gh", lambda args: writes.append(args))

    with pytest.raises(publisher.PublishError):
        publisher.publish(assets, ENV)

    assert writes == []


def test_published_release_rerun_skips_without_writes(tmp_path, monkeypatch):
    assets = make_assets(tmp_path / "release-assets")
    tag = f"preview-{SHA}"
    release = {
        "tag_name": tag,
        "target_commitish": SHA,
        "draft": False,
        "prerelease": True,
        "assets": [{"name": name, "size": 1} for name in publisher.EXPECTED_RELEASE_ASSETS],
    }

    def api(endpoint: str):
        if endpoint.endswith("/commits/main"):
            return {"sha": SHA}
        if endpoint.endswith(f"/releases/tags/{tag}"):
            return release
        if endpoint.endswith(f"/git/ref/tags/{tag}"):
            return {"object": {"type": "commit", "sha": SHA}}
        raise AssertionError(endpoint)

    writes = []
    monkeypatch.setattr(publisher, "_api_get", api)
    monkeypatch.setattr(publisher, "_run_gh", lambda args: writes.append(args))

    assert "already complete" in publisher.publish(assets, ENV)
    assert writes == []


@pytest.mark.parametrize("tag_exists", [True, False])
def test_compatible_partial_draft_reuploads_and_publishes(tmp_path, monkeypatch, tag_exists):
    assets = make_assets(tmp_path / "release-assets")
    tag = f"preview-{SHA}"
    release = {"tag_name": tag, "target_commitish": SHA, "draft": True, "prerelease": True}

    def api(endpoint: str):
        if endpoint.endswith("/commits/main"):
            return {"sha": SHA}
        if endpoint.endswith(f"/releases/tags/{tag}"):
            return None
        if endpoint.endswith(f"/git/ref/tags/{tag}"):
            return {"object": {"type": "commit", "sha": SHA}} if tag_exists else None
        raise AssertionError(endpoint)

    writes = []
    monkeypatch.setattr(publisher, "_api_get", api)
    monkeypatch.setattr(publisher, "_api_get_json", lambda endpoint: [release])
    monkeypatch.setattr(
        publisher,
        "_run_gh",
        lambda args, **kwargs: writes.append(args)
        or subprocess.CompletedProcess(["gh"], 0, "", ""),
    )

    assert publisher.publish(assets, ENV) == f"Published preview release {tag}."
    assert writes[0][:2] == ["release", "upload"]
    assert writes[0][-3:] == ["--clobber", "--repo", publisher.REPOSITORY]
    assert writes[1] == [
        "release",
        "edit",
        tag,
        "--draft=false",
        "--latest=false",
        "--repo",
        publisher.REPOSITORY,
    ]


def test_api_auth_or_network_error_is_not_treated_as_missing(monkeypatch):
    monkeypatch.setattr(
        publisher,
        "_run_gh",
        lambda args: subprocess.CompletedProcess(["gh", *args], 1, "", "authentication failed"),
    )

    with pytest.raises(publisher.PublishError, match="status unknown"):
        publisher._api_get(f"repos/{publisher.REPOSITORY}/releases/tags/preview-{SHA}")


def test_api_404_is_the_only_missing_lookup_result(monkeypatch):
    monkeypatch.setattr(
        publisher,
        "_run_gh",
        lambda args: subprocess.CompletedProcess(
            ["gh", *args],
            1,
            "HTTP/2.0 404 Not Found\r\ncontent-type: application/json\r\n\r\n{}",
            "",
        ),
    )

    assert publisher._api_get(f"repos/{publisher.REPOSITORY}/releases/tags/preview-{SHA}") is None


def test_draft_release_lookup_paginates_until_matching_tag(monkeypatch):
    tag = f"preview-{SHA}"
    first_page = [{"tag_name": f"other-{index}", "draft": False} for index in range(100)]
    draft = {"tag_name": tag, "draft": True}
    pages = {1: first_page, 2: [draft]}
    requested_pages = []

    def get_page(endpoint: str):
        page = int(endpoint.rsplit("=", 1)[1])
        requested_pages.append(page)
        return pages[page]

    monkeypatch.setattr(publisher, "_api_get_json", get_page)

    assert publisher._find_draft_release(tag) == draft
    assert requested_pages == [1, 2]


def test_draft_release_lookup_returns_absent_only_after_last_page(monkeypatch):
    pages = [
        [{"tag_name": f"other-{index}", "draft": False} for index in range(100)],
        [],
    ]
    monkeypatch.setattr(publisher, "_api_get_json", lambda endpoint: pages.pop(0))

    assert publisher._find_draft_release(f"preview-{SHA}") is None
    assert pages == []


def test_draft_release_lookup_fails_closed_on_page_error(monkeypatch):
    first_page = [{"tag_name": f"other-{index}", "draft": False} for index in range(100)]
    requested_pages = []

    def get_page(endpoint: str):
        page = int(endpoint.rsplit("=", 1)[1])
        requested_pages.append(page)
        if page == 2:
            raise publisher.PublishError("GitHub API read failed (status 500).")
        return first_page

    monkeypatch.setattr(publisher, "_api_get_json", get_page)

    with pytest.raises(publisher.PublishError, match="status 500"):
        publisher._find_draft_release(f"preview-{SHA}")
    assert requested_pages == [1, 2]
