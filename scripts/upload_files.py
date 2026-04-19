"""GitHub Contents API 로 파일 업로드 — `requests` 단독 구현.

환경 제약:
- sandbox 에 `gh` CLI 없음
- git push 불가
- api.github.com 은 허용됨

인증:
- 환경변수 `GITHUB_TOKEN` 에 저장소에 contents:write 권한 있는 PAT

사용:
    GITHUB_TOKEN=ghp_xxx python3 scripts/upload_files.py \\
        "커밋 메시지" state/analyzed.json state/state.json
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path

import requests

DEFAULT_REPO = "helen13566-netizen/002-daily-news"
DEFAULT_BRANCH = "main"
API_BASE = "https://api.github.com"


def _token() -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN 환경변수 미설정 — 업로드 불가")
    return token


def _repo() -> str:
    return os.environ.get("DAILY_NEWS_REPO", DEFAULT_REPO)


def _branch() -> str:
    return os.environ.get("DAILY_NEWS_BRANCH", DEFAULT_BRANCH)


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "daily-news-agent/1.0",
    }


def _get_existing_sha(
    repo: str, branch: str, path: str, token: str
) -> str | None:
    url = f"{API_BASE}/repos/{repo}/contents/{path}"
    resp = requests.get(
        url, headers=_headers(token), params={"ref": branch}, timeout=15
    )
    if resp.status_code == 200:
        try:
            return resp.json()["sha"]
        except (KeyError, ValueError):
            return None
    if resp.status_code == 404:
        return None
    # 403 등은 호출 측에 예외로 올려 실패 사유 기록
    raise RuntimeError(
        f"sha 조회 실패 {path}: HTTP {resp.status_code} {resp.text[:300]}"
    )


def upload_one(
    repo: str, branch: str, local_path: str, message: str, token: str
) -> dict:
    p = Path(local_path)
    if not p.is_file():
        raise FileNotFoundError(f"로컬 파일 없음: {local_path}")

    content_b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    sha = _get_existing_sha(repo, branch, local_path, token)

    body: dict[str, object] = {
        "message": message,
        "content": content_b64,
        "branch": branch,
    }
    if sha:
        body["sha"] = sha

    url = f"{API_BASE}/repos/{repo}/contents/{local_path}"
    last_error: str | None = None
    for attempt in range(1, 4):
        try:
            resp = requests.put(
                url, headers=_headers(token), json=body, timeout=30
            )
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            print(
                f"[upload-err {attempt}/3] {local_path}: {last_error}",
                file=sys.stderr,
            )
        else:
            if resp.status_code in (200, 201):
                data = resp.json()
                commit_sha = data.get("commit", {}).get("sha", "?")
                print(
                    f"✓ {local_path} uploaded (commit={commit_sha[:10]}, "
                    f"sha_base={bool(sha)})",
                    file=sys.stderr,
                )
                return data
            last_error = (
                f"HTTP {resp.status_code}: {resp.text[:400]}"
            )
            print(
                f"[upload-err {attempt}/3] {local_path}: {last_error}",
                file=sys.stderr,
            )
        if attempt < 3:
            time.sleep(5 * attempt)

    raise RuntimeError(f"업로드 3회 재시도 실패 {local_path}: {last_error}")


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2

    token = _token()
    message = argv[1]
    files = argv[2:]
    repo = _repo()
    branch = _branch()

    commits: list[str] = []
    for f in files:
        data = upload_one(repo, branch, f, message, token)
        commits.append(data.get("commit", {}).get("sha", "?"))

    print(
        json.dumps(
            {
                "uploaded": files,
                "repo": repo,
                "branch": branch,
                "commits": commits,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
