"""
ATS 도메인에서 Vancouver Product Manager 채용공고를 검색하는 모듈
- Google Custom Search API로 ATS 사이트의 공고를 찾고
- 리스트 페이지/관련 없는 결과를 필터링하고
- 개별 페이지의 구조화 데이터(JSON-LD)에서 상세 정보를 추출합니다
"""

import json
import os
import re
import requests
from datetime import datetime, date, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

# Apify LinkedIn 검색 설정 (APIFY_TOKEN이 없으면 LinkedIn 검색 건너뜀)
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")
APIFY_ACTOR_ID = os.environ.get("APIFY_ACTOR_ID", "worldunboxer/rapid-linkedin-scraper")

# Google Custom Search API 설정
API_KEY = os.environ.get("GOOGLE_API_KEY", "")
SEARCH_ENGINE_ID = os.environ.get("SEARCH_ENGINE_ID", "")

# 웹 요청 시 사용할 브라우저 헤더 (차단 방지)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def search_all_jobs():
    """
    Google Custom Search API + LinkedIn(Apify)로 Product Manager 공고 검색
    1. Google CSE로 ATS 도메인 검색
    2. 리스트 페이지, 관련 없는 공고 필터링
    3. ATS API 우선으로 상세 정보 추출
    4. LinkedIn 검색 결과 병합 (APIFY_TOKEN 있을 때만)
    """
    raw_results = _fetch_search_results()
    filtered = _filter_results(raw_results)
    jobs = _enrich_with_details(filtered)

    # LinkedIn 검색 결과 병합 (URL + title+company 중복 제거)
    linkedin_jobs = _search_linkedin_jobs()
    if linkedin_jobs:
        existing_urls = {j["url"] for j in jobs}
        existing_keys = {(j["title"].lower().strip(), j["company"].lower().strip()) for j in jobs}
        for lj in linkedin_jobs:
            if lj["url"] in existing_urls:
                continue
            dedup_key = (lj["title"].lower().strip(), lj["company"].lower().strip())
            if dedup_key in existing_keys:
                continue
            existing_urls.add(lj["url"])
            existing_keys.add(dedup_key)
            jobs.append(lj)
        jobs.sort(key=lambda j: j.get("date_posted") or "0000-00-00", reverse=True)
        print(f"  LinkedIn 병합 후: {len(jobs)}건")

    return jobs


def _fetch_search_results():
    """Google Custom Search API에서 검색 결과 가져오기"""
    all_items = []
    seen_urls = set()

    # 5가지 직무를 각각 정확한 구문으로 검색
    queries = [
        '"product manager" vancouver',
        '"program manager" vancouver',
        '"project manager" vancouver',
        '"product lead" vancouver',
        '"product operations" vancouver',
        '"product manager" remote canada',
        '"program manager" remote canada',
        '"project manager" remote canada',
        '"product lead" remote canada',
        '"product operations" remote canada',
    ]

    print("  Google Custom Search API로 검색 중...")

    for query in queries:
        print(f"    검색: {query}")
        for start in range(1, 31, 10):  # 쿼리당 최대 30개 (3페이지)
            try:
                params = {
                    "key": API_KEY,
                    "cx": SEARCH_ENGINE_ID,
                    "q": query,
                    "start": start,
                    "dateRestrict": "w1",  # 최근 1주일 내 결과만
                }

                response = requests.get(
                    "https://www.googleapis.com/customsearch/v1",
                    params=params,
                    timeout=15,
                )
                data = response.json()

                if "error" in data:
                    print(f"  API 에러: {data['error']['message']}")
                    break

                items = data.get("items", [])
                if not items:
                    break

                # 쿼리 간 중복 제거 (URL 정규화)
                for item in items:
                    normalized = _clean_job_url(item["link"])
                    if normalized not in seen_urls:
                        seen_urls.add(normalized)
                        all_items.append(item)

                total = int(data.get("searchInformation", {}).get("totalResults", 0))
                if start + 10 > total:
                    break

            except Exception as e:
                print(f"  검색 실패 (start={start}): {e}")
                break

    print(f"  검색 결과: {len(all_items)}건 (중복 제거 후)")
    return all_items


def _clean_job_url(url):
    """
    URL을 JD(채용공고 본문) 페이지로 정리
    - /apply, /applyManually 등 지원 프로세스 경로 제거
    - 불필요한 쿼리 파라미터 제거
    """
    # 쿼리 파라미터 제거
    url = url.split("?")[0]
    # Workday: /apply, /applyManually 등 제거
    url = re.sub(r"/apply(/applyManually)?/?$", "", url)
    # Ashby/Greenhouse: /application 제거
    url = re.sub(r"/application/?$", "", url)
    # 끝의 슬래시 제거
    url = url.rstrip("/")
    return url


def _filter_results(items):
    """
    검색 결과에서 노이즈 제거:
    - 리스트/회사 페이지 제외 (개별 공고만 남김)
    - Product Manager와 관련 없는 직무 제외
    - URL 기준 중복 제거
    """
    filtered = []

    for item in items:
        url = item["link"]
        title = item.get("title", "")
        snippet = item.get("snippet", "")

        # 리스트 페이지 제외 (개별 공고가 아닌 페이지)
        if _is_list_page(url, title, snippet):
            continue

        # Product Manager와 관련 없는 직무 제외
        if not _is_pm_related(title):
            continue

        filtered.append(item)

    print(f"  필터링 후: {len(filtered)}건")
    return filtered


def _is_list_page(url, title, snippet):
    """
    리스트/회사 페이지인지 판별
    (이전 auto-job-search 프로젝트의 isListPage 로직 기반)
    """
    url_lower = url.lower()
    title_lower = title.lower()
    snippet_lower = snippet.lower()

    # URL 패턴: 회사 채용 목록 페이지
    list_patterns = [
        r"/jobs\?",        # /jobs?source=...
        r"/careers\?",     # /careers?source=...
        r"/jobs/?$",       # /jobs 또는 /jobs/ (끝)
        r"/careers/?$",    # /careers 또는 /careers/ (끝)
    ]
    if any(re.search(p, url_lower) for p in list_patterns):
        return True

    # 제목: 목록 페이지 키워드
    list_titles = [
        "all jobs", "open positions", "careers", "job board",
        "current openings", "jobs at", "explore current opportunities",
        "insights and opportunities",
    ]
    if any(kw in title_lower for kw in list_titles):
        return True

    # Wellfound 회사/펀딩/역할 페이지
    if "wellfound.com" in url_lower:
        if "/role/" in url_lower or "/funding" in url_lower:
            return True
        # /company/xxx 또는 /company/xxx/jobs (개별 공고 ID 없음)
        if re.search(r"wellfound\.com/company/[^/]+(/(jobs)?)?$", url_lower):
            return True

    # 스니펫: 여러 직무가 나열된 경우
    if any(kw in snippet_lower for kw in ["view all", "see more", "browse all"]):
        return True

    # Workday 비영어 페이지 제외 — locale 경로가 있으면 en-US/en만 허용
    if "myworkdayjobs.com" in url_lower:
        locale_match = re.search(r"/([a-z]{2}(?:[-_][A-Z]{2})?)/", url)
        if locale_match:
            locale = locale_match.group(1).lower()
            if not locale.startswith("en"):
                return True

    return False


def _is_pm_related(title):
    """Product/Program/Project Manager 관련 직무인지 확인"""
    title_lower = title.lower()
    pm_keywords = [
        "product manager", "product management",
        "program manager", "program management",
        "project manager", "project management",
        "product lead",
        "product operations",
    ]
    return any(kw in title_lower for kw in pm_keywords)


def _enrich_with_details(items):
    """
    각 검색 결과의 실제 채용 페이지에서 상세 정보 추출 후
    위치 조건 필터링:
    - Remote: Canada 어디든 OK
    - On-site/Hybrid: Vancouver 광역권이어야 함
    - 위치 정보 없음: 페이지 본문에서 밴쿠버/캐나다 근무지 여부 확인
    """
    jobs = []
    seen_titles = set()  # 제목+회사 기준 중복 제거

    for item in items:
        url = _clean_job_url(item["link"])  # JD 본문 페이지로 정리
        # Google 검색 결과 title 정리
        google_title = item.get("title", "")
        # 사이트명 제거 (예: "... - Myworkdayjobs.com", "... - Greenhouse")
        google_title = re.sub(r"\s*[-–|].*\.(com|ca|co|io|org).*$", "", google_title)
        google_title = re.sub(r"\s*[-–|]\s*(Greenhouse|TELUS Jobs|Jobs|Career Opportunities).*$", "", google_title, flags=re.I)
        # Greenhouse 패턴: "Job Application for {직무} at {회사}" → 직무만 추출
        google_title = re.sub(r"^Job Application for\s+", "", google_title, flags=re.I)
        google_title = re.sub(r"\s+at\s+.+$", "", google_title)

        job = {
            "title": google_title.strip(),
            "company": _extract_company_from_url(url),
            "location": "",
            "employment_type": "",
            "date_posted": "",
            "url": url,
        }

        # 상세 정보 추출: ATS API 우선, HTML 스크래핑 fallback
        page_text = ""

        # 1차: ATS 공개 API (Greenhouse / Lever / Ashby / SmartRecruiters)
        api_data = _fetch_from_ats_api(url)
        if api_data:
            for key in ["title", "company", "location", "date_posted"]:
                if api_data.get(key):
                    job[key] = api_data[key]

        # 2차: HTML 스크래핑 (API 없거나 location / date 누락 시)
        if not job["location"] or not job["date_posted"]:
            details = _extract_job_details(url)
            if details:
                page_text = details.pop("_page_text", "")
                for key in ["title", "company", "location", "employment_type", "date_posted"]:
                    if details.get(key) and not job[key]:
                        job[key] = details[key]

        # 게시일 기준 필터링: 7일 이내만 (날짜 정보 없으면 유지)
        if not _passes_date_filter(job["date_posted"]):
            continue

        # 위치 조건 필터링
        if job["location"]:
            # 위치 정보가 있으면 기존 필터 적용
            if not _passes_location_filter(job["location"]):
                continue
        else:
            # 위치 정보가 없으면 페이지 본문에서 밴쿠버/캐나다 근무지 여부 확인
            if not _verify_location_from_text(page_text):
                continue

        # 제목+회사 기준 중복 제거
        dedup_key = (job["title"].lower().strip(), job["company"].lower().strip())
        if dedup_key in seen_titles:
            continue
        seen_titles.add(dedup_key)

        jobs.append(job)

    # 최신순 정렬 (date_posted 있는 것 먼저, 없는 것은 뒤로)
    jobs.sort(key=lambda j: j.get("date_posted") or "0000-00-00", reverse=True)

    print(f"  날짜+위치 필터 후: {len(jobs)}건")
    return jobs


# Vancouver 광역권 도시 목록
VANCOUVER_METRO = [
    "vancouver", "north vancouver", "west vancouver", "burnaby",
    "richmond", "surrey", "new westminster", "coquitlam",
    "port coquitlam", "port moody", "delta", "langley",
    "maple ridge", "pitt meadows", "white rock",
]

# 캐나다 주(Province) 코드 및 이름
CANADA_PROVINCES = [
    "bc", "on", "qc", "ab", "mb", "sk", "ns", "nb", "nl", "pe", "yt", "nt", "nu",
    "british columbia", "ontario", "quebec", "alberta", "manitoba",
    "saskatchewan", "nova scotia", "new brunswick", "newfoundland",
    "prince edward island", "yukon", "northwest territories", "nunavut",
]


def _passes_date_filter(date_posted, max_days=7):
    """
    게시일 기준 필터:
    - datePosted가 있으면 7일 이내만 통과
    - datePosted가 없으면 통과 (benefit of the doubt)
    """
    if not date_posted:
        return True
    try:
        posted = date.fromisoformat(date_posted[:10])
        today = datetime.now(ZoneInfo("America/Vancouver")).date()
        return (today - posted).days <= max_days
    except (ValueError, TypeError):
        return True


def _verify_location_from_text(page_text):
    """
    위치 정보가 없는 공고의 페이지 본문에서 밴쿠버/캐나다 근무지 여부 확인
    - "vancouver" 포함 → 통과
    - "canada"만 있고 "remote" 포함 → 통과 (Remote Canada)
    - 둘 다 없음 → 제외
    """
    if not page_text:
        return False

    # "vancouver"가 있으면 Canada/BC인지 확인 (미국 Vancouver, WA 제외)
    if "vancouver" in page_text:
        if "canada" in page_text or "british columbia" in page_text or re.search(r'\bbc\b', page_text):
            return True

    # "canada"만 있고 "remote" 포함 → Remote Canada
    if "canada" in page_text and "remote" in page_text:
        return True

    # "namer" + "remote" 포함 → Remote North America (Canada 포함으로 간주)
    if "namer" in page_text and "remote" in page_text:
        return True

    return False


NON_CANADA_KEYWORDS = [
    "united states", "u.s.", "usa",
    "united kingdom", "u.k.", "england", "scotland", "wales",
    "mexico",
    "australia",
    "india",
    "europe",
    "brazil",
    "germany",
    "france",
]


def _passes_location_filter(location):
    """
    위치 조건 필터:
    - Remote → Canada 명시 또는 국가 미지정이면 통과 / 비캐나다 국가 명시면 제외
    - On-site/Hybrid → Vancouver 광역권이어야 함
    - 위치 정보 없음 → 통과 (benefit of the doubt)
    """
    if not location:
        return True

    loc_lower = location.lower()
    is_remote = "remote" in loc_lower or "flexible" in loc_lower

    if is_remote:
        if "namer" in loc_lower:
            return True
        # Canada 명시 → 통과 (US도 함께 언급된 경우 포함)
        if "canada" in loc_lower or _is_in_canada(loc_lower):
            return True
        # Canada 없이 비캐나다 국가 명시 → 제외
        if re.search(r'\bus\b', loc_lower):
            return False
        if any(kw in loc_lower for kw in NON_CANADA_KEYWORDS):
            return False
        # 국가 미지정 → 통과 (Google CSE가 이미 Canada 범위로 검색)
        return True
    else:
        return _is_in_vancouver_metro(loc_lower)


def _is_in_canada(location_lower):
    """캐나다 위치인지 확인"""
    if "canada" in location_lower:
        return True
    # 주 코드/이름 확인 (예: "BC", "Ontario")
    for province in CANADA_PROVINCES:
        # 단어 경계로 매칭 (예: "bc"가 "pubbc" 같은 데서 매칭되지 않도록)
        if re.search(r'\b' + re.escape(province) + r'\b', location_lower):
            return True
    return False


def _is_in_vancouver_metro(location_lower):
    """Vancouver 광역권인지 확인 (VANCOUVER_METRO 목록에 있는 도시만)"""
    for city in VANCOUVER_METRO:
        if city in location_lower:
            return True
    return False


def _extract_company_from_url(url):
    """URL 패턴에서 회사명 추출 (ATS마다 URL 구조가 다름)"""
    try:
        parts = url.replace("https://", "").replace("http://", "").split("/")
        domain = parts[0]

        # 예: jobs.lever.co/회사명/job-id
        if domain in [
            "jobs.lever.co",
            "job-boards.greenhouse.io",
            "jobs.ashbyhq.com",
            "jobs.smartrecruiters.com",
        ]:
            if len(parts) > 1:
                # 쿼리 파라미터 제거 후 회사명 추출
                company = parts[1].split("?")[0]
                return company.replace("-", " ").title()

        # 예: wellfound.com/company/회사명/jobs/...
        if "wellfound.com" in domain:
            if "company" in parts and len(parts) > parts.index("company") + 1:
                company = parts[parts.index("company") + 1].split("?")[0]
                return company.replace("-", " ").title()
    except Exception:
        pass

    # Fallback: 도메인에서 회사명 추출
    # 예: amazon.jobs → Amazon, careers.microsoft.com → Microsoft
    try:
        domain = urlparse(url).netloc.lower()
        # jobs/careers 서브도메인 패턴: careers.회사.com, jobs.회사.com, www.careers.회사.com
        m = re.match(r"(?:www\.)?(?:careers|jobs|job)\.([^.]+)\.", domain)
        if m:
            return m.group(1).replace("-", " ").title()
        # 회사.jobs 패턴: amazon.jobs, www.amazon.jobs
        m = re.match(r"(?:www\.)?([^.]+)\.jobs$", domain)
        if m:
            return m.group(1).replace("-", " ").title()
    except Exception:
        pass

    return ""


def _extract_job_details(url):
    """
    개별 채용 페이지에서 상세 정보 추출
    1차: JSON-LD 구조화 데이터(schema.org/JobPosting)
    2차: HTML microdata (property 속성) — Job Bank 등
    3차: HTML class에서 위치 힌트 추출
    """
    try:
        response = requests.get(url, timeout=10, headers=HEADERS)
        soup = BeautifulSoup(response.text, "html.parser")

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)

                # 데이터가 리스트인 경우 JobPosting 항목 찾기
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("@type") == "JobPosting":
                            data = item
                            break
                    else:
                        continue

                # @graph 안에 있는 경우
                if isinstance(data, dict) and "@graph" in data:
                    for item in data["@graph"]:
                        if isinstance(item, dict) and item.get("@type") == "JobPosting":
                            data = item
                            break
                    else:
                        continue

                if not isinstance(data, dict) or data.get("@type") != "JobPosting":
                    continue

                return {
                    "title": data.get("title", ""),
                    "company": _parse_company(data),
                    "location": _parse_location(data),
                    "employment_type": _parse_employment_type(
                        data.get("employmentType", "")
                    ),
                    "date_posted": data.get("datePosted", ""),
                    "_page_text": soup.get_text(separator=" ", strip=True).lower(),
                }
            except (json.JSONDecodeError, AttributeError, TypeError):
                continue

        # JSON-LD 없는 경우: microdata(property 속성)에서 추출 시도
        microdata = _extract_from_microdata(soup)
        if microdata:
            microdata["_page_text"] = soup.get_text(separator=" ", strip=True).lower()
            return microdata

        # microdata도 없는 경우: HTML class에서 위치 힌트만 추출
        location_hint = _extract_location_from_html(soup)
        page_text = soup.get_text(separator=" ", strip=True).lower()
        return {"location": location_hint, "_page_text": page_text}

    except Exception:
        pass

    return None


def _extract_from_microdata(soup):
    """
    HTML microdata (property 속성)에서 채용 정보 추출
    Job Bank 등 JSON-LD 대신 microdata를 사용하는 사이트용
    """
    def _get_prop(name):
        el = soup.find(attrs={"property": name})
        if el:
            return el.get_text(strip=True)
        return ""

    # title이 있어야 채용 페이지로 판단
    title = _get_prop("title")
    if not title:
        return None

    # 위치: addressLocality + addressRegion
    locality = _get_prop("addressLocality")
    region = _get_prop("addressRegion")
    location_parts = [p for p in [locality, region] if p]
    location = ", ".join(location_parts)

    # 회사명: hiringOrganization 하위의 name
    company = ""
    org_el = soup.find(attrs={"property": "hiringOrganization"})
    if org_el:
        name_el = org_el.find(attrs={"property": "name"})
        if name_el:
            company = name_el.get_text(strip=True)

    # 고용형태 (Job Bank: "Permanent employmentFull time" → 정리)
    emp_type = _get_prop("employmentType")
    emp_type = emp_type.replace("employment", "employment, ")

    # 게시일
    date_posted = _get_prop("datePosted")
    # Job Bank 형식: "Posted on March 10, 2026" → 날짜만 추출
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", date_posted)
    if not date_match:
        # "March 10, 2026" 형식 파싱
        date_match = re.search(r"([A-Z][a-z]+ \d{1,2},?\s*\d{4})", date_posted)
        if date_match:
            try:
                parsed = datetime.strptime(date_match.group(1).replace(",", ""), "%B %d %Y")
                date_posted = parsed.strftime("%Y-%m-%d")
            except ValueError:
                date_posted = ""
        else:
            date_posted = ""
    else:
        date_posted = date_match.group(1)

    return {
        "title": title,
        "company": company,
        "location": location,
        "employment_type": emp_type,
        "date_posted": date_posted,
    }


def _extract_location_from_html(soup):
    """
    JSON-LD가 없는 페이지에서 위치 정보를 추출
    일반적인 ATS 페이지의 위치 표시 패턴을 찾습니다
    """
    # class/id에 "location" 포함된 요소에서 도시, 주, 국가 형태의 텍스트 찾기
    candidates = []
    for el in soup.find_all(attrs={"class": re.compile(r"location", re.I)}):
        text = el.get_text(strip=True)
        if text and 5 < len(text) < 200:
            candidates.append(text)

    for el in soup.find_all(attrs={"id": re.compile(r"location", re.I)}):
        text = el.get_text(strip=True)
        if text and 5 < len(text) < 200:
            candidates.append(text)

    # 가장 구체적인 위치 텍스트 반환 (쉼표가 있으면 "도시, 주, 국가" 형태일 가능성 높음)
    for c in candidates:
        if "," in c:
            return c
    return candidates[0] if candidates else ""


def _parse_company(data):
    """JSON-LD에서 회사명 추출"""
    org = data.get("hiringOrganization", {})
    if isinstance(org, dict):
        return org.get("name", "")
    return ""


def _parse_location(data):
    """JSON-LD에서 근무지 추출"""
    location = data.get("jobLocation", {})

    if isinstance(location, list):
        location = location[0] if location else {}

    if isinstance(location, dict):
        address = location.get("address", {})
        if isinstance(address, dict):
            parts = []
            if address.get("addressLocality"):
                parts.append(address["addressLocality"])
            if address.get("addressRegion"):
                parts.append(address["addressRegion"])
            if parts:
                if data.get("jobLocationType") == "TELECOMMUTE":
                    return ", ".join(parts) + " (Remote)"
                return ", ".join(parts)
        elif isinstance(address, str):
            return address

    if data.get("jobLocationType") == "TELECOMMUTE":
        return "Remote"

    return ""


def _parse_employment_type(emp_type):
    """고용 형태를 읽기 좋게 변환 (예: FULL_TIME → Full-time)"""
    if not emp_type:
        return ""

    mapping = {
        "FULL_TIME": "Full-time",
        "PART_TIME": "Part-time",
        "CONTRACT": "Contract",
        "TEMPORARY": "Temporary",
        "INTERN": "Internship",
        "OTHER": "",
    }

    if isinstance(emp_type, list):
        types = [mapping.get(t, t) for t in emp_type if mapping.get(t, t)]
        return ", ".join(types)
    return mapping.get(emp_type, emp_type)


# ──────────────────────────────────────────────
# ATS 공개 API 직접 연동
# ──────────────────────────────────────────────

def _fetch_from_ats_api(url):
    """URL 패턴을 보고 ATS 공개 API를 직접 호출해서 상세 정보 반환"""
    try:
        # Greenhouse: job-boards.greenhouse.io/{company}/jobs/{job_id}
        m = re.match(r'https://job-boards\.greenhouse\.io/([^/]+)/jobs/(\d+)', url)
        if m:
            return _fetch_greenhouse(m.group(1), m.group(2))

        # Lever: jobs.lever.co/{company}/{uuid}
        m = re.match(r'https://jobs\.lever\.co/([^/]+)/([0-9a-f-]{36})', url)
        if m:
            return _fetch_lever(m.group(1), m.group(2))

        # Ashby: jobs.ashbyhq.com/{company}/{uuid}
        m = re.match(r'https://jobs\.ashbyhq\.com/([^/]+)/([0-9a-f-]{36})', url)
        if m:
            return _fetch_ashby(m.group(1), m.group(2))

        # SmartRecruiters: jobs.smartrecruiters.com/{company}/{job_id}
        m = re.match(r'https://jobs\.smartrecruiters\.com/([^/]+)/(\d+)', url)
        if m:
            return _fetch_smartrecruiters(m.group(1), m.group(2))

    except Exception as e:
        print(f"  ATS API 실패 ({url}): {e}")

    return None


def _fetch_greenhouse(company, job_id):
    """Greenhouse 공개 API로 특정 공고 정보 조회"""
    url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{job_id}"
    r = requests.get(url, timeout=10, headers=HEADERS)
    data = r.json()

    location = data.get("location", {}).get("name", "")
    # published_at 우선, 없으면 updated_at fallback
    date_posted = (data.get("published_at") or data.get("updated_at") or "")[:10]

    return {
        "title": data.get("title", ""),
        "location": location,
        "date_posted": date_posted,
    }


def _fetch_lever(company, job_id):
    """Lever 공개 API로 특정 공고 정보 조회"""
    url = f"https://api.lever.co/v0/postings/{company}/{job_id}"
    r = requests.get(url, timeout=10, headers=HEADERS)
    data = r.json()

    categories = data.get("categories", {})
    location = categories.get("location", "")

    # createdAt은 milliseconds timestamp
    date_posted = ""
    created_at = data.get("createdAt")
    if created_at:
        dt = datetime.fromtimestamp(created_at / 1000, tz=ZoneInfo("UTC"))
        date_posted = dt.strftime("%Y-%m-%d")

    return {
        "title": data.get("text", ""),
        "location": location,
        "date_posted": date_posted,
    }


def _fetch_ashby(company, job_id):
    """Ashby 공개 API로 특정 공고 정보 조회 (전체 목록에서 ID로 검색)"""
    url = f"https://api.ashbyhq.com/posting-api/job-board/{company}/published"
    r = requests.get(url, timeout=10, headers=HEADERS)
    data = r.json()

    job = next((j for j in data.get("jobs", []) if j.get("id") == job_id), None)
    if not job:
        return None

    # location: Place schema
    loc = job.get("location")
    location = loc.get("name", "") if isinstance(loc, dict) else (loc or "")
    if job.get("isRemote"):
        location = (location + " (Remote)") if location else "Remote"

    # publishedAt: "2021-04-30T16:21:55.393+00:00"
    date_posted = (job.get("publishedAt") or "")[:10]

    return {
        "title": job.get("title", ""),
        "location": location,
        "date_posted": date_posted,
    }


def _fetch_smartrecruiters(company, job_id):
    """SmartRecruiters 공개 API로 특정 공고 정보 조회"""
    url = f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{job_id}"
    r = requests.get(url, timeout=10, headers=HEADERS)
    data = r.json()

    loc = data.get("location", {})
    parts = [p for p in [loc.get("city"), loc.get("region"), loc.get("country")] if p]
    location = ", ".join(parts)
    if loc.get("remote"):
        location = (location + " (Remote)") if location else "Remote"

    # releasedDate: "2026-03-15"
    date_posted = (data.get("releasedDate") or "")[:10]

    return {
        "title": data.get("name", ""),
        "company": data.get("company", {}).get("name", ""),
        "location": location,
        "date_posted": date_posted,
    }


# ──────────────────────────────────────────────
# Apify LinkedIn 검색
# ──────────────────────────────────────────────

def _search_linkedin_jobs():
    """
    Apify LinkedIn Jobs Scraper로 LinkedIn 공고 검색
    - APIFY_TOKEN 환경변수가 없으면 건너뜀
    - 기본 actor: worldunboxer/rapid-linkedin-scraper (APIFY_ACTOR_ID로 변경 가능)
    """
    if not APIFY_TOKEN:
        return []

    print("  LinkedIn(Apify) 검색 중...")
    try:
        # Vancouver(on-site/hybrid) + Canada Remote 두 번 검색 후 합산
        all_items = []
        searches = [
            {"location": "Vancouver, BC"},
            {"location": "Canada", "work_schedule": "Remote"},
        ]
        for search_params in searches:
            actor_input = {
                "searchTerms": [
                    "product manager",
                    "program manager",
                    "project manager",
                    "product lead",
                    "product operations",
                ],
                "maxItems": 50,
                **search_params,
            }
            api_url = (
                f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}"
                f"/run-sync-get-dataset-items?token={APIFY_TOKEN}&timeout=300"
            )
            response = requests.post(api_url, json=actor_input, timeout=320)
            if response.ok and isinstance(response.json(), list):
                all_items.extend(response.json())

        if not all_items:
            print("  LinkedIn 응답 없음")
            return []

        jobs = []
        seen_urls = set()

        for item in all_items:
            # worldunboxer/rapid-linkedin-scraper 필드명
            title = item.get("job_title") or item.get("jobTitle") or item.get("title") or ""
            company = item.get("company_name") or item.get("companyName") or item.get("company") or ""
            location = item.get("location") or ""
            job_url = item.get("job_url") or item.get("jobUrl") or item.get("url") or ""
            posted_at = item.get("time_posted") or item.get("postedAt") or item.get("postedDate") or ""

            if not job_url or job_url in seen_urls:
                continue

            date_posted = _parse_linkedin_date(posted_at)

            job = {
                "title": title,
                "company": company,
                "location": location,
                "employment_type": "",
                "date_posted": date_posted,
                "url": job_url,
            }

            if not _is_pm_related(title):
                continue
            if job["location"] and not _passes_location_filter(job["location"]):
                continue
            if not _passes_date_filter(job["date_posted"]):
                continue

            seen_urls.add(job_url)
            jobs.append(job)

        print(f"  LinkedIn 결과: {len(jobs)}건")
        return jobs

    except Exception as e:
        print(f"  LinkedIn 검색 실패: {e}")
        return []


def _parse_linkedin_date(date_str):
    """LinkedIn 상대 날짜 → YYYY-MM-DD 변환 ('2 days ago', 'Just now' 등)"""
    if not date_str:
        return ""
    s = str(date_str).strip().lower()
    today = datetime.now(ZoneInfo("America/Vancouver")).date()

    if any(w in s for w in ["just", "moment", "hour", "minute", "second"]):
        return today.isoformat()

    m = re.search(r'(\d+)\s*day', s)
    if m:
        return (today - timedelta(days=int(m.group(1)))).isoformat()

    m = re.search(r'(\d+)\s*week', s)
    if m:
        return (today - timedelta(days=int(m.group(1)) * 7)).isoformat()

    m = re.search(r'(\d+)\s*month', s)
    if m:
        return (today - timedelta(days=int(m.group(1)) * 30)).isoformat()

    # ISO date 또는 절대 날짜
    try:
        return date.fromisoformat(s[:10]).isoformat()
    except ValueError:
        return ""
