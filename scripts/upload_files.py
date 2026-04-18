"""GitHub Contents API 로 파일을 원격 저장소에 업로드.

Sandbox 환경의 remote agent 가 `git push` 를 사용할 수 없을 때
`gh api` 로 directly 저장소 main 브랜치에 파일을 쓰기 위한 스크립트.

사용:
    python3 scripts/upload_files.py "커밋 메시지" state/analyzed.json state/state.json
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_REPO = "helen13566-netizen/002-daily-news"
DEFAULT_BRANCH = "main"


def _repo() -> str:
    return os.environ.get("DAILY_NEWS_REPO", DEFAULT_REPO)


def _branch() -> str:
    return os.environ.get("DAILY_NEWS_BRANCH", DEFAULT_BRANCH)


def _get_existing_sha(repo: str, branch: str, path: str) -> str | None:
    # gh api 는 GET 에서 -f 를 쿼리로 자동 변환하지 않는 경우가 있어 URL 에 직접 포함.
    result = subprocess.run(
        [
            "gh", "api",
            f"/repos/{repo}/contents/{path}?ref={branch}",
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # 404 = 신규 파일, 기타 = 에러 로그
        if "404" not in result.stderr:
            print(f"[sha 조회 경고] {path}: {result.stderr.strip()}", file=sys.stderr)
        return None
    try:
        return json.loads(result.stdout)["sha"]
    except (KeyError, json.JSONDecodeError):
        return None


def upload_one(repo: str, branch: str, local_path: str, message: str) -> None:
    p = Path(local_path)
    if not p.is_file():
        raise FileNotFoundError(f"로컬 파일 없음: {local_path}")

    content_b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    sha = _get_existing_sha(repo, branch, local_path)

    args = [
        "gh", "api", "-X", "PUT",
        f"/repos/{repo}/contents/{local_path}",
        "-f", f"message={message}",
        "-f", f"branch={branch}",
        "-f", f"content={content_b64}",
    ]
    if sha:
        args += ["-f", f"sha={sha}"]

    print(f"→ uploading {local_path} ({len(content_b64)} b64 chars, existing_sha={sha})",
          file=sys.stderr)
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"업로드 실패 {local_path}:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )
    response = json.loads(result.stdout)
    commit_sha = response.get("commit", {}).get("sha", "?")
    print(f"✓ {local_path} uploaded (commit={commit_sha[:10]})", file=sys.stderr)


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2

    message = argv[1]
    files = argv[2:]
    repo = _repo()
    branch = _branch()

    for f in files:
        upload_one(repo, branch, f, message)

    print(json.dumps({"uploaded": files, "repo": repo, "branch": branch}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
