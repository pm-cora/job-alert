"""
Gmail API를 사용하여 채용공고 알림 이메일을 발송하는 모듈
- OAuth 2.0 인증 사용 (App Password 대신 Google 공식 인증 방식)
- 처음 실행 시 브라우저에서 Google 로그인이 필요합니다 (1회만)
"""

import os
import base64
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# Gmail 발송 권한 scope
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

# 수신자 이메일
TO_EMAIL = "REDACTED"

# 인증 파일 경로 (이 스크립트와 같은 폴더에 위치)
CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json")
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token.json")


def get_gmail_service():
    """
    Gmail API 서비스 객체 생성
    - token.json이 있으면 저장된 인증 정보 사용
    - 없거나 만료되면 브라우저로 로그인 (최초 1회)
    """
    creds = None

    # 저장된 토큰이 있으면 로드
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    # 토큰이 없거나 만료된 경우
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # 만료된 토큰 자동 갱신
            creds.refresh(Request())
        else:
            # GitHub Actions 등 CI 환경에서는 브라우저 로그인 불가
            if os.environ.get("CI"):
                raise RuntimeError(
                    "토큰이 만료되었습니다. 로컬에서 다시 인증 후 GitHub Secret을 업데이트하세요."
                )
            # 새로 로그인 (브라우저가 열림)
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        # 갱신된 토큰 저장 (다음번에는 자동 로그인)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def build_email_body(jobs):
    """채용공고 목록을 이메일 HTML 본문으로 변환"""
    today = datetime.now(ZoneInfo("America/Vancouver")).strftime("%Y-%m-%d")

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto; color: #333;">
        <h2 style="color: #2c3e50;">Caroline's Job Alert — {today}</h2>
        <p style="color: #666;">
            Total <strong>{len(jobs)}</strong> new postings found (past 7 days)
        </p>
        <hr style="border: 1px solid #eee;">
    """

    for i, job in enumerate(jobs, 1):
        # 각 공고를 카드 형태로 표시
        html += f"""
        <div style="margin: 20px 0; padding: 15px; border: 1px solid #e0e0e0; border-radius: 8px;">
            <h3 style="margin: 0 0 8px 0; color: #2c3e50;">{i}. {job['title']}</h3>
        """

        if job.get("company"):
            html += f'<p style="margin: 4px 0;">Company: {job["company"]}</p>'

        if job.get("location"):
            html += f'<p style="margin: 4px 0;">Location: {job["location"]}</p>'

        if job.get("salary"):
            html += f'<p style="margin: 4px 0;">Salary: {job["salary"]}</p>'

        if job.get("employment_type"):
            html += f'<p style="margin: 4px 0;">Type: {job["employment_type"]}</p>'

        posted_label = _format_days_ago(job.get("date_posted", ""))

        html += f"""
            <a href="{job['url']}" style="display: inline-block; margin-top: 12px; padding: 8px 20px;
               background-color: #3498db; color: #ffffff; text-decoration: none;
               border-radius: 5px; font-size: 14px; font-weight: bold;">
                View posting
            </a>
        """

        if posted_label:
            html += f'<span style="margin-left: 12px; color: #999; font-size: 12px;">{posted_label}</span>'

        html += """
        </div>
        """

    html += """
        <hr style="border: 1px solid #eee;">
        <p style="color: #bbb; font-size: 11px;">
            Search: "Product/Program/Project Manager" in Vancouver, Canada<br>
            Sources: Greenhouse, Lever, Workday, SmartRecruiters, Ashby + 10 sites<br>
            "X days ago" = actual posting date from the job page
        </p>
    </body>
    </html>
    """

    return html


def _format_days_ago(date_posted):
    """날짜 문자열(YYYY-MM-DD)을 'today', '1 day ago', '3 days ago' 등으로 변환"""
    if not date_posted:
        return ""
    try:
        posted = date.fromisoformat(date_posted[:10])
        today = datetime.now(ZoneInfo("America/Vancouver")).date()
        diff = (today - posted).days
        if diff == 0:
            return "today"
        elif diff == 1:
            return "1 day ago"
        elif diff > 1:
            return f"{diff} days ago"
    except (ValueError, TypeError):
        pass
    return ""


def send_email(subject, html_body):
    """Gmail API로 이메일 발송"""
    service = get_gmail_service()

    # HTML 이메일 메시지 생성
    message = MIMEMultipart("alternative")
    message["to"] = TO_EMAIL
    message["subject"] = subject

    html_part = MIMEText(html_body, "html")
    message.attach(html_part)

    # Base64 인코딩 후 Gmail API로 발송
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service.users().messages().send(
        userId="me",
        body={"raw": raw},
    ).execute()
