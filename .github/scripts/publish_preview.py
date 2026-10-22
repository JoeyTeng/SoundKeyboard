#!/usr/bin/env python3
"""Publish a commit-specific preview release from validated CI build assets."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPOSITORY = "JoeyTeng/SoundKeyboard"
EXPECTED_ASSETS = (
    "SoundKeyboard-windows-x86_64.exe",
    "SoundKeyboard-macos-arm64.app.zip",
    "SoundKeyboard-macos-x86_64.app.zip",
)
EXPECTED_RELEASE_ASSETS = (*EXPECTED_ASSETS, "LICENSE", "SHA256SUMS.txt")
GH_TIMEOUT_SECONDS = 30
GH_UPLOAD_TIMEOUT_SECONDS = 180
RELEASES_PAGE_SIZE = 100
RELEASES_MAX_PAGES = 100


class PublishError(Exception):
    """Raised when release metadata or a GitHub operation is unsafe to continue."""


def _run_gh(args: list[str], timeout: int = GH_TIMEOUT_SECONDS) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["gh", *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PublishError(f"GitHub CLI call failed: {type(exc).__name__}") from exc


def _response_status(result: subprocess.CompletedProcess[str]) -> int | None:
    text = f"{result.stdout}\n{result.stderr}"
    statuses = re.findall(r"(?m)^HTTP/\S+\s+(\d{3})\b", text)
    if statuses:
        return int(statuses[-1])
    statuses = re.findall(r"\bHTTP\s+(\d{3})\b", text)
    return int(statuses[-1]) if statuses else None


def _api_get_json(endpoint: str) -> Any | None:
    result = _run_gh(["api", "--include", endpoint])
    status = _response_status(result)
    if result.returncode != 0:
        if status == 404:
            return None
        raise PublishError(f"GitHub API read failed (status {status or 'unknown'}).")
    if status is None or not 200 <= status < 300:
        raise PublishError(f"GitHub API returned unexpected status {status or 'unknown'}.")

    # --include emits response headers followed by the JSON body. Select the
    # body after the last header separator to tolerate intermediate redirects.
    body = result.stdout.rsplit("\r\n\r\n", 1)[-1]
    if body == result.stdout:
        body = result.stdout.rsplit("\n\n", 1)[-1]
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise PublishError("GitHub API returned invalid JSON.") from exc
    return payload


def _api_get(endpoint: str) -> dict[str, Any] | None:
    payload = _api_get_json(endpoint)
    if payload is not None and not isinstance(payload, dict):
        raise PublishError("GitHub API returned an unexpected response shape.")
    return payload


def _find_draft_release(tag: str) -> dict[str, Any] | None:
    endpoint = f"repos/{REPOSITORY}/releases"
    matches = []
    for page in range(1, RELEASES_MAX_PAGES + 1):
        payload = _api_get_json(f"{endpoint}?per_page={RELEASES_PAGE_SIZE}&page={page}")
        if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
            raise PublishError("GitHub release list returned an unexpected response shape.")
        matches.extend(item for item in payload if item.get("tag_name") == tag)
        if len(matches) > 1:
            raise PublishError("GitHub returned duplicate releases for the preview tag.")
        if len(payload) < RELEASES_PAGE_SIZE:
            break
    else:
        raise PublishError("GitHub release listing exceeded the safe pagination limit.")

    if not matches:
        return None
    if matches[0].get("draft") is not True:
        raise PublishError("A release-list entry exists but the published tag lookup missed it.")
    return matches[0]


def _find_release(tag: str) -> dict[str, Any] | None:
    release = _api_get(f"repos/{REPOSITORY}/releases/tags/{tag}")
    if release is not None:
        return release
    return _find_draft_release(tag)


def _validated_environment(env: dict[str, str]) -> tuple[str, str]:
    if env.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise PublishError("Refusing to publish from an unexpected repository.")
    if env.get("GITHUB_EVENT_NAME") != "push" or env.get("GITHUB_REF") != "refs/heads/main":
        raise PublishError("Refusing to publish outside a push to refs/heads/main.")
    sha = env.get("GITHUB_SHA", "")
    run_id = env.get("GITHUB_RUN_ID", "")
    if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", sha):
        raise PublishError("GITHUB_SHA must be a full hexadecimal commit ID.")
    if not re.fullmatch(r"[1-9][0-9]*", run_id):
        raise PublishError("GITHUB_RUN_ID must be a positive integer.")
    return sha.lower(), run_id


def _current_main_sha() -> str:
    response = _api_get(f"repos/{REPOSITORY}/commits/main")
    sha = response.get("sha") if response else None
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", sha):
        raise PublishError("Could not verify the current main commit.")
    return sha.lower()


def _validate_binaries(directory: Path) -> dict[str, Path]:
    if not directory.is_dir():
        raise PublishError("The release-assets directory is missing.")
    try:
        entries = list(directory.iterdir())
    except OSError as exc:
        raise PublishError("Could not read release-assets directory.") from exc
    names = {entry.name for entry in entries}
    if names != set(EXPECTED_ASSETS):
        missing = sorted(set(EXPECTED_ASSETS) - names)
        unexpected = sorted(names - set(EXPECTED_ASSETS))
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected: {', '.join(unexpected)}")
        raise PublishError(
            "Release assets do not match the expected set (" + "; ".join(details) + ")."
        )

    binaries: dict[str, Path] = {}
    for name in EXPECTED_ASSETS:
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise PublishError(f"Release asset is not a non-empty regular file: {name}")
        binaries[name] = path
    return binaries


def _tag_commit(tag: str) -> str | None:
    response = _api_get(f"repos/{REPOSITORY}/git/ref/tags/{tag}")
    if response is None:
        return None
    obj = response.get("object")
    if not isinstance(obj, dict) or not isinstance(obj.get("sha"), str):
        raise PublishError("Git tag lookup returned an unexpected response shape.")
    sha = obj["sha"]
    if obj.get("type") == "commit":
        return sha.lower()
    if obj.get("type") != "tag":
        raise PublishError("Preview tag does not point to a commit.")
    annotated = _api_get(f"repos/{REPOSITORY}/git/tags/{sha}")
    target = annotated.get("object") if annotated else None
    if (
        not isinstance(target, dict)
        or target.get("type") != "commit"
        or not isinstance(target.get("sha"), str)
    ):
        raise PublishError("Annotated preview tag does not resolve to a commit.")
    return target["sha"].lower()


def _prepare_assets(
    work_dir: Path, binaries: dict[str, Path], sha: str, run_id: str, repo_root: Path
) -> tuple[list[Path], Path]:
    for name, source in binaries.items():
        shutil.copyfile(source, work_dir / name)
    license_path = repo_root / "LICENSE"
    notes_path = repo_root / ".github" / "RELEASE_NOTES.md"
    if not license_path.is_file() or not notes_path.is_file():
        raise PublishError("LICENSE or .github/RELEASE_NOTES.md is missing.")
    shutil.copyfile(license_path, work_dir / "LICENSE")

    sums = []
    for name in (*EXPECTED_ASSETS, "LICENSE"):
        digest = hashlib.sha256((work_dir / name).read_bytes()).hexdigest()
        sums.append(f"{digest}  {name}")
    (work_dir / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")

    notes = notes_path.read_text(encoding="utf-8").rstrip()
    run_url = f"https://github.com/{REPOSITORY}/actions/runs/{run_id}"
    notes += f"\n\nSource commit: `{sha}`\nCI run: {run_url}\n"
    prepared_notes = work_dir / "release-notes.md"
    prepared_notes.write_text(notes, encoding="utf-8")
    return [work_dir / name for name in EXPECTED_RELEASE_ASSETS], prepared_notes


def _release_assets_valid(release: dict[str, Any]) -> bool:
    assets = release.get("assets")
    if not isinstance(assets, list):
        return False
    found: dict[str, int] = {}
    for asset in assets:
        if isinstance(asset, dict) and isinstance(asset.get("name"), str):
            size = asset.get("size")
            found[asset["name"]] = size if isinstance(size, int) else 0
    return all(found.get(name, 0) > 0 for name in EXPECTED_RELEASE_ASSETS)


def _upload(tag: str, files: list[Path]) -> None:
    result = _run_gh(
        [
            "release",
            "upload",
            tag,
            *(str(path) for path in files),
            "--clobber",
            "--repo",
            REPOSITORY,
        ],
        timeout=GH_UPLOAD_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise PublishError("Could not upload preview release assets.")


def publish(asset_directory: Path, env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    sha, run_id = _validated_environment(env)
    if _current_main_sha() != sha:
        return "Source commit is no longer current on main; skipped preview publication."

    binaries = _validate_binaries(asset_directory)
    repo_root = Path(__file__).resolve().parents[2]
    tag = f"preview-{sha}"
    with tempfile.TemporaryDirectory(prefix="soundkeyboard-preview-") as temp_dir:
        files, notes_path = _prepare_assets(Path(temp_dir), binaries, sha, run_id, repo_root)
        release = _find_release(tag)
        tag_sha = _tag_commit(tag)

        if release is not None:
            if release.get("tag_name") != tag or release.get("target_commitish") != sha:
                raise PublishError("Existing preview release targets a different commit.")
            if release.get("draft") is False:
                if tag_sha != sha:
                    raise PublishError("Existing preview tag targets a different commit.")
                if release.get("prerelease") is not True or not _release_assets_valid(release):
                    raise PublishError(
                        "Existing published preview release is incomplete or incompatible."
                    )
                return f"Preview release {tag} is already complete; skipped unchanged."
            if release.get("draft") is not True or release.get("prerelease") is not True:
                raise PublishError("Existing draft preview release is incompatible.")
            if tag_sha is not None and tag_sha != sha:
                raise PublishError("Existing preview tag targets a different commit.")
            _upload(tag, files)
        else:
            if tag_sha is not None and tag_sha != sha:
                raise PublishError("Existing preview tag targets a different commit.")
            create = _run_gh(
                [
                    "release",
                    "create",
                    tag,
                    "--draft",
                    "--prerelease",
                    "--title",
                    f"SoundKeyboard preview {sha[:12]}",
                    "--notes-file",
                    str(notes_path),
                    "--target",
                    sha,
                    "--repo",
                    REPOSITORY,
                ]
            )
            if create.returncode != 0:
                raise PublishError("Could not create preview release draft.")
            _upload(tag, files)

        publish_result = _run_gh(
            [
                "release",
                "edit",
                tag,
                "--draft=false",
                "--latest=false",
                "--repo",
                REPOSITORY,
            ]
        )
        if publish_result.returncode != 0:
            raise PublishError("Assets uploaded, but the preview draft could not be published.")
    return f"Published preview release {tag}."


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("Usage: python .github/scripts/publish_preview.py release-assets", file=sys.stderr)
        return 2
    try:
        print(publish(Path(argv[0])))
        return 0
    except PublishError as exc:
        print(f"Preview publication failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
