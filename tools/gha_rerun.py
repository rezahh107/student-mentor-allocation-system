#!/usr/bin/env python3
"""Trigger GitHub Actions workflow re-runs with retries and Persian output."""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional


API_ROOT = "https://api.github.com"

BACKOFFS = [0.060, 0.120, 0.240]


class RerunError(RuntimeError):
    """Domain-specific exception for rerun CLI."""


@dataclass
class GitHubContext:
    repository: str
    branch: str
    workflow: str
    token: str


def _persian_error(code: str, message: str) -> RerunError:
    return RerunError(f"{code}: {message}")


def _redact_url(raw: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(raw)
        netloc = parsed.hostname or ""
        if parsed.port:
            netloc += f":{parsed.port}"
        query = parsed.query
        if query:
            query = re.sub(r"(token|access_token)=[^&]+", r"\1=***", query, flags=re.IGNORECASE)
        return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, query, parsed.fragment))
    except Exception:  # pragma: no cover - best effort sanitization
        return raw


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise _persian_error("RERUN_HTTP_FAILED", f"متغیر {name} خالی است")
    return value


def _detect_branch() -> str:
    import subprocess

    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        raise _persian_error(
            "RERUN_HTTP_FAILED",
            f"git branch خوانده نشد: {result.stderr.strip()}",
        )
    return result.stdout.strip()


def _get_context(args: argparse.Namespace) -> GitHubContext:
    token = _env("GITHUB_TOKEN")
    repository = args.repository or _env("GITHUB_REPOSITORY")
    branch = args.branch or _detect_branch()
    workflow = args.workflow
    return GitHubContext(repository=repository, branch=branch, workflow=workflow, token=token)


def _request(url: str, method: str, token: str, data: Optional[dict] = None) -> tuple[int, dict]:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}" if token else "",
        "User-Agent": "gha-rerun-cli",
    }
    payload = None
    if data is not None:
        payload = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=payload, headers=headers, method=method)
    attempt = 0
    while True:
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
                decoded = json.loads(body.decode("utf-8")) if body else {}
                return response.getcode(), decoded
        except urllib.error.HTTPError as error:
            status = error.getcode()
            if status >= 500 and attempt < len(BACKOFFS):
                _sleep_with_jitter(attempt)
                attempt += 1
                continue
            detail = error.read().decode("utf-8", "ignore")
            safe_url = _redact_url(error.geturl() or url)
            if status in (401, 403):
                raise _persian_error(
                    "RERUN_AUTH_FAILED",
                    f"دسترسی به {safe_url} با وضعیت {status} رد شد؛ توکن/مجوز را بررسی کنید",
                )
            if status == 404:
                raise _persian_error(
                    "RERUN_NOT_FOUND",
                    f"منبع مورد نظر در {safe_url} با وضعیت 404 یافت نشد",
                )
            raise _persian_error(
                "RERUN_HTTP_FAILED",
                f"درخواست به {safe_url} با وضعیت {status} شکست خورد: {detail}",
            )
        except (urllib.error.URLError, ConnectionError, EOFError) as error:
            if attempt < len(BACKOFFS):
                _sleep_with_jitter(attempt)
                attempt += 1
                continue
            raise _persian_error(
                "RERUN_HTTP_FAILED",
                f"اتصال به {_redact_url(url)} برقرار نشد: {error}",
            )


def _sleep_with_jitter(attempt: int) -> None:
    base = BACKOFFS[min(attempt, len(BACKOFFS) - 1)]
    jitter = random.uniform(0, base / 5)
    time.sleep(base + jitter)


def _list_runs(ctx: GitHubContext) -> dict:
    workflow_path = ctx.workflow
    url = (
        f"{API_ROOT}/repos/{ctx.repository}/actions/workflows/"
        f"{workflow_path}/runs?branch={ctx.branch}&per_page=1"
    )
    status, payload = _request(url, "GET", ctx.token)
    if status != 200:
        raise _persian_error("RERUN_HTTP_FAILED", f"فهرست اجراها با وضعیت {status} بازگشت")
    return payload


def _rerun(ctx: GitHubContext, run_id: int) -> tuple[int, dict]:
    url = f"{API_ROOT}/repos/{ctx.repository}/actions/runs/{run_id}/rerun"
    status, payload = _request(url, "POST", ctx.token, data={})
    if status not in (201, 202):
        raise _persian_error("RERUN_HTTP_FAILED", f"درخواست rerun با وضعیت {status} رد شد")
    return status, payload


def _extract_latest_run(payload: dict) -> int:
    runs = payload.get("workflow_runs")
    if not runs:
        raise _persian_error("RERUN_HTTP_FAILED", "هیچ اجرای فعالی برای شاخه یافت نشد")
    run_id = runs[0].get("id")
    if not run_id:
        raise _persian_error("RERUN_HTTP_FAILED", "شناسه اجرا خالی بود")
    return int(run_id)


def _persian_summary(status: int, run_id: int, html_url: str) -> str:
    return f"وضعیت: {status} | شناسه اجرا: {run_id} | نشانی: {html_url}"


def run(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Trigger GitHub Actions rerun")
    parser.add_argument("--workflow", default="ci.yml", help="نام فایل گردش‌کار")
    parser.add_argument("--run-id", type=int, help="شناسه اجرای مورد نظر")
    parser.add_argument("--repository", help="مخزن owner/repo")
    parser.add_argument("--branch", help="شاخه هدف")
    args = parser.parse_args(argv)

    ctx = _get_context(args)

    run_id = args.run_id
    if run_id is None:
        payload = _list_runs(ctx)
        run_id = _extract_latest_run(payload)
        html_url = payload["workflow_runs"][0].get("html_url", "")
    else:
        html_url = (
            f"https://github.com/{ctx.repository}/actions/runs/{run_id}"  # deterministic
        )

    status, response = _rerun(ctx, run_id)
    print(
        "DEBUG: "
        f"repository={ctx.repository} branch={ctx.branch} workflow={ctx.workflow} run_id={run_id}"
    )
    summary = _persian_summary(status, run_id, response.get("message", html_url) or html_url)
    print(summary)
    return 0


def main() -> int:  # pragma: no cover
    try:
        return run()
    except RerunError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
