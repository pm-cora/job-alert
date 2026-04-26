"""
Gmail SMTP를 사용하여 채용공고 알림 이메일을 발송하는 모듈
- Gmail App Password 방식 (토큰 만료 없음)
"""

import os
import smtplib
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from zoneinfo import ZoneInfo

SMTP_USER = os.environ.get("GMAIL_USER", "")
SMTP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

TO_EMAIL = ["REDACTED", "REDACTED"]


def send_email(subject, html_body):
    """Gmail SMTP로 이메일 발송"""
    message = MIMEMultipart("alternative")
    message["From"] = SMTP_USER
    message["Bcc"] = ", ".join(TO_EMAIL)
    message["Subject"] = subject

    message.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, TO_EMAIL, message.as_string())


def build_email_body(jobs, seen_urls=None):
    """채용공고 목록을 이메일 HTML 본문으로 변환"""
    if seen_urls is None:
        seen_urls = set()
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
        is_seen = job["url"] in seen_urls
        btn_color = "#aaaaaa" if is_seen else "#3498db"

        html += f"""
        <div style="margin: 20px 0; padding: 15px; border: 1px solid #e0e0e0; border-radius: 8px;">
            <h3 style="margin: 0 0 8px 0; color: #2c3e50;">{i}. {job['title']}</h3>
        """

        if job.get("company"):
            html += f'<p style="margin: 4px 0;">Company: {job["company"]}</p>'

        if job.get("location"):
            html += f'<p style="margin: 4px 0;">Location: {_simplify_location(job["location"])}</p>'

        if job.get("employment_type"):
            html += f'<p style="margin: 4px 0;">Type: {job["employment_type"]}</p>'

        posted_label = _format_days_ago(job.get("date_posted", ""))

        html += f"""
            <a href="{job['url']}" style="display: inline-block; margin-top: 12px; padding: 8px 20px;
               background-color: {btn_color}; color: #ffffff; text-decoration: none;
               border-radius: 5px; font-size: 14px; font-weight: bold;">
                View posting
            </a>
        """

        if posted_label:
            html += f'<span style="margin-left: 12px; color: #999; font-size: 12px;">{posted_label}</span>'

        for kw in job.get("keywords", []):
            html += f'<span style="margin-left: 8px; padding: 2px 8px; background-color: #eaf4fb; color: #2980b9; border-radius: 4px; font-size: 12px;">{kw}</span>'

        html += """
        </div>
        """

    html += """
        <hr style="border: 1px solid #eee;">
        <p style="color: #bbb; font-size: 11px;">
            Search: "Product/Program/Project Manager", "Product Lead", "Product Operations" in Vancouver &amp; Remote Canada<br>
            Sources: Greenhouse, Lever, Workday, SmartRecruiters, Ashby + 10 sites, LinkedIn<br>
            "X days ago" = actual posting date from the job page
        </p>
    </body>
    </html>
    """

    return html


VANCOUVER_METRO_CITIES = [
    "vancouver", "north vancouver", "west vancouver", "burnaby",
    "richmond", "surrey", "new westminster", "coquitlam",
    "port coquitlam", "port moody", "delta", "langley",
    "maple ridge", "pitt meadows", "white rock",
]


def _simplify_location(location):
    """위치를 간소화: 밴쿠버 광역 도시명 또는 Remote만 표시"""
    if not location:
        return ""
    loc_lower = location.lower()

    is_remote = "remote" in loc_lower or "flexible" in loc_lower

    found_city = None
    for city in VANCOUVER_METRO_CITIES:
        if city in loc_lower:
            found_city = city.title()
            break

    if "namer" in loc_lower:
        return "Remote, Canada (NAMER)"

    if is_remote and found_city:
        return f"{found_city} (Remote)"
    elif is_remote:
        return "Remote, Canada"
    elif found_city:
        return found_city
    else:
        return location


def _format_days_ago(date_posted):
    """날짜 문자열(YYYY-MM-DD)을 'today', '1 day ago', '3 days ago' 등으로 변환"""
    if not date_posted:
        return "within 7 days (by Google)"
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
    return "within 7 days (by Google)"
