"""
Vancouver Product Manager 채용공고 자동 알림 스크립트
- ATS 도메인에서 최근 7일 내 공고를 검색
- 결과를 이메일로 발송
"""

import os
from datetime import datetime
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


def main():
    # 밴쿠버 시간 기준
    now_van = datetime.now(ZoneInfo("America/Vancouver"))
    print(f"검색 시작... ({now_van.strftime('%Y-%m-%d %H:%M')} Vancouver time)")

    # 모든 ATS 도메인에서 채용공고 검색
    jobs = search_all_jobs()

    if not jobs:
        print("검색된 공고가 없습니다.")
        return

    print(f"총 {len(jobs)}건의 공고 발견")
    for i, job in enumerate(jobs, 1):
        print(f"  {i}. [{job.get('date_posted','')}] {job['title']} | {job.get('company','')} | {job.get('location','')} | {job['url']}")

    # 이메일 본문 생성 및 발송
    subject = f"Caroline's Job Alert — {now_van.strftime('%Y-%m-%d')}"
    body = build_email_body(jobs)
    send_email(subject, body)

    print("이메일 발송 완료!")


if __name__ == "__main__":
    main()
