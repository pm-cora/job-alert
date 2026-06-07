"""
Vancouver Product Manager 채용공고 자동 알림 스크립트
- ATS 도메인에서 최근 7일 내 공고를 검색
- 결과를 이메일로 발송
"""

import json
import os
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# .env 파일이 있으면 환경변수로 로드 (로컬 실행용)
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

from job_search import search_all_jobs
from email_sender import send_email, build_email_body

SEEN_JOBS_FILE = Path(__file__).parent / "seen_jobs.json"
CONFIG_FILE = Path(__file__).parent / "config.json"

def _load_config():
    if not CONFIG_FILE.exists():
        return {"enabled": True, "recipients": [], "title_keywords": [], "content_keywords": []}
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {"enabled": True, "recipients": [], "title_keywords": [], "content_keywords": []}


def _load_seen_urls():
    if not SEEN_JOBS_FILE.exists():
        return {}
    try:
        return json.loads(SEEN_JOBS_FILE.read_text()).get("seen", {})
    except Exception:
        return {}


def _save_seen_urls(jobs, prev_seen):
    today = date.today().isoformat()
    cutoff = (date.today() - timedelta(days=30)).isoformat()
    seen = {url: d for url, d in prev_seen.items() if d >= cutoff}
    for job in jobs:
        if job["url"] not in seen:
            seen[job["url"]] = today
    SEEN_JOBS_FILE.write_text(json.dumps({"seen": seen}, indent=2, ensure_ascii=False))


def main():
    config = _load_config()
    if not config.get("enabled", True):
        print("알림 비활성화 상태입니다. (config.json enabled=false)")
        return

    recipients = config.get("recipients") or []
    if not recipients:
        print("수신자가 없습니다. Gist에서 recipients를 설정하세요.")
        return

    now_van = datetime.now(ZoneInfo("America/Vancouver"))
    print(f"검색 시작... ({now_van.strftime('%Y-%m-%d %H:%M')} Vancouver time)")
    print(f"수신자: {', '.join(recipients)}")

    seen_map = _load_seen_urls()
    seen_urls = set(seen_map.keys())

    title_keywords = config.get("title_keywords") or []
    content_keywords = config.get("content_keywords") or []
    jobs = search_all_jobs(
        title_keywords=title_keywords or None,
        content_keywords=content_keywords or None,
    )

    if not jobs:
        print("검색된 공고가 없습니다.")
        return

    print(f"총 {len(jobs)}건의 공고 발견")
    for i, job in enumerate(jobs, 1):
        label = "(재등장)" if job["url"] in seen_urls else "(신규)"
        print(f"  {i}. {label} [{job.get('date_posted','')}] {job['title']} | {job.get('company','')} | {job.get('location','')} | {job['url']}")

    subject = f"Caroline's Job Alert — {now_van.strftime('%Y-%m-%d')}"
    body = build_email_body(jobs, seen_urls)
    send_email(subject, body, recipients)

    _save_seen_urls(jobs, seen_map)
    print("이메일 발송 완료!")


if __name__ == "__main__":
    main()
