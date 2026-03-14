import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.formula1.com"
CALENDAR_URL = "https://www.formula1.com/en/racing/2026"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
}


@dataclass
class DriverResult:
    pos: str
    driver: str
    team: str
    # Practice 세션: time_gap 사용
    time_gap: Optional[str] = None
    # Qualifying 세션: q1, q2, q3 사용
    q1: Optional[str] = None
    q2: Optional[str] = None
    q3: Optional[str] = None
    # Race 세션: pts 사용
    pts: Optional[str] = None

@dataclass
class SessionItem:
    session: str
    start_datetime_local: Optional[str]
    end_datetime_local: Optional[str]
    results: Optional[list[DriverResult]] = None

@dataclass
class EventItem:
    round: Optional[int]
    status: str
    event_type: str
    title: str
    country: str
    date_range_text: str
    start_date_local: Optional[str]
    end_date_local: Optional[str]
    event_url: str
    cancellation_reason: Optional[str] = None
    sessions: list = None

    def __post_init__(self):
        if self.sessions is None:
            self.sessions = []


MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def get_soup(url: str) -> BeautifulSoup:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def extract_round(text: str) -> Optional[int]:
    match = re.search(r"ROUND\s+(\d+)", text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def extract_location_from_title(title: str) -> str:
    """풀 타이틀에서 지역/국가명만 추출 (Title Case).

    예시:
      "FORMULA 1 QATAR AIRWAYS AUSTRALIAN GRAND PRIX 2026" → "Australian"
      "FORMULA 1 HEINEKEN SILVER LAS VEGAS GRAND PRIX 2026" → "Las Vegas"
      "FORMULA 1 LENOVO JAPANESE GRAND PRIX 2026" → "Japanese"
      "PRE-SEASON TESTING 2026" → "Pre-Season Testing"  (GRAND PRIX 없으면 원본 반환)
    """
    # "GRAND PRIX" 앞에 오는 단어(들)를 추출
    match = re.search(r"FORMULA\s+1\s+.+?\s+((?:[A-Z]+\s+)+)GRAND\s+PRIX", title.upper())
    if match:
        # 스폰서명 제거: FORMULA 1 다음 단어들 중 지역명은 보통 마지막 1~3 단어
        # 전략: "GRAND PRIX" 바로 앞 단어(들)를 뒤에서부터 취함
        # 고유명사 지역은 1~3 단어 (e.g. "LAS VEGAS", "SAO PAULO", "AUSTRALIAN")
        before_gp = match.group(1).strip().split()
        # 스폰서(단일 단어 대문자)는 제거하고 지역명(1~3 단어) 취득
        # 간단히: 마지막 단어가 형용사형(-AN, -ESE, -IAN)이면 1단어, 아니면 최대 2단어 취득
        if len(before_gp) >= 1:
            last = before_gp[-1]
            if re.search(r"(AN|ESE|IAN|ISH|CH)$", last, re.IGNORECASE):
                location = last.title()
            elif len(before_gp) >= 2:
                location = " ".join(before_gp[-2:]).title()
            else:
                location = last.title()
            return location
    # GRAND PRIX가 없는 경우 (Testing 등) → 원본을 Title Case로
    return title.title()


def parse_date_range_text(date_range_text: str, year: int = 2026) -> tuple[Optional[str], Optional[str]]:
    """
    Examples:
    - '06 - 08 Mar'
    - '30 Oct - 01 Nov'
    - '11 - 13 Feb'
    """
    text = clean_text(date_range_text)
    text = text.replace("Sept", "Sep")

    same_month = re.match(r"(\d{1,2})\s*-\s*(\d{1,2})\s*([A-Za-z]{3})", text)
    if same_month:
        start_day = int(same_month.group(1))
        end_day = int(same_month.group(2))
        month = MONTHS[same_month.group(3).upper()]
        start_date = datetime(year, month, start_day).strftime("%Y-%m-%d")
        end_date = datetime(year, month, end_day).strftime("%Y-%m-%d")
        return start_date, end_date

    cross_month = re.match(r"(\d{1,2})\s*([A-Za-z]{3})\s*-\s*(\d{1,2})\s*([A-Za-z]{3})", text)
    if cross_month:
        start_day = int(cross_month.group(1))
        start_month = MONTHS[cross_month.group(2).upper()]
        end_day = int(cross_month.group(3))
        end_month = MONTHS[cross_month.group(4).upper()]
        start_date = datetime(year, start_month, start_day).strftime("%Y-%m-%d")
        end_date = datetime(year, end_month, end_day).strftime("%Y-%m-%d")
        return start_date, end_date

    return None, None


def parse_time_range(time_text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Examples:
    - '10:30 - 11:30'
    - '13:00'
    """
    text = clean_text(time_text)

    range_match = re.match(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", text)
    if range_match:
        return range_match.group(1), range_match.group(2)

    single_match = re.match(r"(\d{1,2}:\d{2})$", text)
    if single_match:
        return single_match.group(1), None

    return None, None


def to_iso_local(date_str: Optional[str], time_str: Optional[str]) -> Optional[str]:
    if not date_str or not time_str:
        return None
    return f"{date_str}T{time_str}:00"


def get_cancellation_reason(event_url: str) -> Optional[str]:
    """취소된 이벤트 페이지에서 'IMPORTANT UPDATE' 다음에 오는 취소 사유 텍스트를 추출.
    
    HTML 구조:
      IMPORTANT UPDATE\n<취소 사유 텍스트>\nREAD MORE
    """
    try:
        soup = get_soup(event_url)
        text_lines = [clean_text(l) for l in soup.get_text("\n").splitlines() if clean_text(l)]
        for i, line in enumerate(text_lines):
            if line.upper() == "IMPORTANT UPDATE":
                # IMPORTANT UPDATE 바로 다음 라인이 취소 사유
                if i + 1 < len(text_lines):
                    reason = text_lines[i + 1]
                    # "READ MORE" 같은 버튼 텍스트가 아닌 경우에만 반환
                    if reason.upper() not in ("READ MORE", ""):
                        return reason
        return None
    except Exception:
        return None


def parse_event_sessions(event_url: str) -> list[SessionItem]:
    soup = get_soup(event_url)
    
    # 세션별 Results 링크 찾기 매핑
    result_links = {}
    for a_tag in soup.select("a"):
        href = a_tag.get("href", "")
        text = a_tag.get_text(strip=True)
        if text.upper() == "RESULTS" and "/results/" in href.lower():
            href_lower = href.lower()
            full_url = urljoin(BASE_URL, href)
            if href_lower.endswith("/practice/1"): result_links["Practice 1"] = full_url
            elif href_lower.endswith("/practice/2"): result_links["Practice 2"] = full_url
            elif href_lower.endswith("/practice/3"): result_links["Practice 3"] = full_url
            elif href_lower.endswith("/qualifying"): result_links["Qualifying"] = full_url
            elif href_lower.endswith("/race-result"): result_links["Race"] = full_url
            elif href_lower.endswith("/sprint-qualifying"): result_links["Sprint Qualifying"] = full_url
            elif href_lower.endswith("/sprint") or href_lower.endswith("/sprint-results"): result_links["Sprint"] = full_url

    # 텍스트 라인 단위로 나누기
    text_lines = [clean_text(line) for line in soup.get_text("\n").splitlines()]
    text_lines = [line for line in text_lines if line]

    session_names = {
        "Practice 1",
        "Practice 2",
        "Practice 3",
        "Sprint Qualifying",
        "Sprint",
        "Qualifying",
        "Race",
    }

    sessions: list[SessionItem] = []
    
    for i, line in enumerate(text_lines):
        if line in session_names:
            session_name = line
            
            # 1) 시간 정보는 세션명 '바로 아래' 줄들에 위치
            # 예: [ "Practice 1", "01:30", "-", "02:30" ]
            # 또는 [ "Race", "04:00", "Expand" ]
            start_time = None
            end_time = None
            
            if i + 1 < len(text_lines):
                candidate_start = text_lines[i + 1]
                if re.match(r"^\d{1,2}:\d{2}$", candidate_start):
                    start_time = candidate_start
            
            if start_time and i + 3 < len(text_lines):
                if text_lines[i + 2] == "-":
                    candidate_end = text_lines[i + 3]
                    if re.match(r"^\d{1,2}:\d{2}$", candidate_end):
                        end_time = candidate_end
                        
            # 만약 "XX:XX - YY:YY"가 하나의 라인에 모여 있다면 (예방 차원)
            if start_time is None and i + 1 < len(text_lines):
                p_start, p_end = parse_time_range(text_lines[i + 1])
                if p_start:
                    start_time = p_start
                    end_time = p_end

            # 2) 날짜 정보는 세션명 '위쪽'에 위치
            # 예: [ "06", "Mar", "Chequered Flag", "Practice 1" ]
            date_day = None
            date_month = None
            
            for back in range(1, 5):
                if i - back < 0:
                    break
                candidate = text_lines[i - back]
                
                # 월 찾기
                if not date_month and candidate.upper() in MONTHS:
                    date_month = MONTHS[candidate.upper()]
                # 일 찾기 (한두자리 숫자)
                elif not date_day and re.fullmatch(r"\d{1,2}", candidate):
                    date_day = int(candidate)

            date_str = None
            if date_day is not None and date_month is not None:
                date_str = datetime(2026, date_month, date_day).strftime("%Y-%m-%d")

            session_result_url = result_links.get(session_name)
            session_results = get_session_results(session_result_url, session_name) if session_result_url else None

            sessions.append(
                SessionItem(
                    session=session_name,
                    start_datetime_local=to_iso_local(date_str, start_time),
                    end_datetime_local=to_iso_local(date_str, end_time),
                    results=session_results,
                )
            )

    # 중복 제거 (순서 유지): 세션명(s.session) 기준
    unique_sessions_dict = {}
    for s in sessions:
        # 시간 정보가 없는 경우(웹페이지 하단 하이라이트 등 잘못 파싱된 세션)는 제외
        if s.start_datetime_local is None and s.end_datetime_local is None:
            continue
            
        if s.session not in unique_sessions_dict:
            unique_sessions_dict[s.session] = s
        else:
            # 기존 항목에 시간이 없고 새 항목에 시간이 있다면 교체 (혹시 모를 예외 방지)
            if s.start_datetime_local and not unique_sessions_dict[s.session].start_datetime_local:
                unique_sessions_dict[s.session] = s

    return list(unique_sessions_dict.values())


def _extract_driver_name(col) -> str:
    """HTML 클래스 기반으로 드라이버 성/이름 추출 (약자 제외).
    F1 사이트 구조:
      <span class="max-lg:hidden">Charles</span>  ← First name
      <span class="max-md:hidden">Leclerc</span>  ← Last name
      <span class="md:hidden">LEC</span>           ← 약자 (무시)
    """
    import re
    first_span = col.select_one("span.max-lg\\:hidden")
    last_span  = col.select_one("span.max-md\\:hidden")
    if first_span and last_span:
        return f"{first_span.get_text(strip=True)} {last_span.get_text(strip=True)}"
    # 폴백: 전체 텍스트에서 대문자 3자리 약자 제거
    raw = " ".join(col.stripped_strings)
    return re.sub(r'\s*\b[A-Z]{3}\b\s*', ' ', raw).strip()


def get_session_results(result_url: str, session_name: str = "Race") -> Optional[list[DriverResult]]:
    """세션 타입별 결과 데이터 파싱.
    - Practice 1/2/3: Pos, Driver, Team, Time/Gap
    - Qualifying: Pos, Driver, Team, Q1, Q2, Q3
    - Race: Pos, Driver, Team, Time/Retired, Pts
    """
    # 테이블 컬럼 구조:
    # Race:        [Pos, No, Driver, Team, Laps, Time/Retired, Pts]
    # Practice:    [Pos, No, Driver, Team, Time/Gap, Laps]
    # Qualifying:  [Pos, No, Driver, Team, Q1, Q2, Q3, Laps]
    try:
        r_soup = get_soup(result_url)
        table = r_soup.select_one("table")
        if not table:
            return None

        is_practice = session_name.startswith("Practice")
        is_qualifying = session_name in ("Qualifying", "Sprint Qualifying")
        # 나머지는 Race, Sprint

        results: list[DriverResult] = []
        for row in table.select("tbody tr"):
            cols = row.select("td")
            if len(cols) < 4:
                continue

            pos    = cols[0].get_text(strip=True)
            driver = _extract_driver_name(cols[2] if len(cols) > 2 else cols[1])
            team   = cols[3].get_text(strip=True) if len(cols) > 3 else ""

            if is_practice:
                # [Pos, No, Driver, Team, Time/Gap, Laps]
                time_gap = cols[4].get_text(strip=True) if len(cols) > 4 else None
                results.append(DriverResult(pos=pos, driver=driver, team=team, time_gap=time_gap))

            elif is_qualifying:
                # [Pos, No, Driver, Team, Q1, Q2, Q3, Laps]
                q1 = cols[4].get_text(strip=True) if len(cols) > 4 else None
                q2 = cols[5].get_text(strip=True) if len(cols) > 5 else None
                q3 = cols[6].get_text(strip=True) if len(cols) > 6 else None
                results.append(DriverResult(pos=pos, driver=driver, team=team, q1=q1, q2=q2, q3=q3))

            else:
                # Race: [Pos, No, Driver, Team, Laps, Time/Retired, Pts]
                pts = cols[6].get_text(strip=True) if len(cols) > 6 else None
                results.append(DriverResult(pos=pos, driver=driver, team=team, pts=pts))

        return results if results else None
    except Exception:
        return None

def parse_calendar() -> list[EventItem]:
    soup = get_soup(CALENDAR_URL)

    # event_url을 키로 하여 파싱된 데이터를 임시 저장
    events_map = {}

    for a_tag in soup.select('a[href*="/en/racing/2026/"]'):
        href = a_tag.get("href")
        if not href:
            continue

        full_url = urljoin(BASE_URL, href)
        text = clean_text(" ".join(a_tag.stripped_strings))
        status = "Cancelled" if re.search(r'(Cancel|Called Off)', text, re.IGNORECASE) else "Scheduled"

        if "/en/racing/2026/pre-season-testing-" in href:
            title_match = re.search(r"(FORMULA 1 .*? 2026)", text)
            date_match = re.search(r"(\d{1,2}\s*-\s*\d{1,2}\s*[A-Za-z]{3})", text)
            title = title_match.group(1) if title_match else text
            date_range_text = date_match.group(1) if date_match else ""
            
            # 더 긴(정확한) 타이틀로 업데이트
            if full_url in events_map:
                if len(title) > len(events_map[full_url]["title"]):
                    events_map[full_url]["title"] = title
                if status == "Cancelled":
                    events_map[full_url]["status"] = "Cancelled"
            else:
                events_map[full_url] = {
                    "round": None,
                    "status": status,
                    "event_type": "testing",
                    "title": title,
                    "country": "Bahrain",
                    "date_range_text": date_range_text,
                    "event_url": full_url,
                }
            continue

        round_match = re.search(r"ROUND\s+(\d+)", text, re.IGNORECASE)
        # 만약 링크 텍스트에 "ROUND"나 "FORMULA 1" 둘 다 없다면 스킵
        if not round_match and "FORMULA 1" not in text.upper():
            continue

        round_no = int(round_match.group(1)) if round_match else None
        
        title_match = re.search(r"(FORMULA 1 .*? 2026)", text)
        date_match = re.search(
            r"(\d{1,2}\s*-\s*\d{1,2}\s*[A-Za-z]{3}|\d{1,2}\s*[A-Za-z]{3}\s*-\s*\d{1,2}\s*[A-Za-z]{3})",
            text
        )

        title = title_match.group(1) if title_match else text
        date_range_text = date_match.group(1) if date_match else ""

        # 링크 텍스트 parts 예시:
        # ["ROUND 4", "Chequered Flag", "Flag of Bahrain", "Bahrain", "FORMULA 1 ..."]
        # ["ROUND 6", "NEXT RACE", "Flag of United States of America", "Miami", "FORMULA 1 ..."]
        # "Flag of ..." 바로 다음 항목이 실제 지역명
        country = ""
        location_title = ""
        parts = [clean_text(x) for x in a_tag.stripped_strings]
        for idx, part in enumerate(parts):
            if part.startswith("Flag of ") and idx + 1 < len(parts):
                location_title = parts[idx + 1]   # e.g. "Australia", "Las Vegas", "Miami"
                country = parts[idx].replace("Flag of ", "")  # e.g. "Australia", "United States of America"
                break
        # location_title을 못 찾으면 country 기반으로 폴백
        if not location_title:
            for idx, part in enumerate(parts):
                if part.upper().startswith("ROUND") and idx + 1 < len(parts):
                    country = parts[idx + 1]
                    location_title = country
                    break

        if full_url in events_map:
            existing = events_map[full_url]
            if status == "Cancelled":
                existing["status"] = "Cancelled"
            if not existing["round"] and round_no:
                existing["round"] = round_no
            if not existing["country"] and country:
                existing["country"] = country
            if not existing["location_title"] and location_title:
                existing["location_title"] = location_title
            if not existing["date_range_text"] and date_range_text:
                existing["date_range_text"] = date_range_text
        else:
            events_map[full_url] = {
                "round": round_no,
                "status": status,
                "event_type": "grand_prix",
                "title": title,
                "location_title": location_title,
                "country": country,
                "date_range_text": date_range_text,
                "event_url": full_url,
            }

    events: list[EventItem] = []
    
    # 이제 모아둔 URL별 데이터로 세션 파싱을 진행 (세션 파싱은 각 URL별로 한 번만)
    for url, data in events_map.items():
        start_date, end_date = parse_date_range_text(data["date_range_text"])
        parsed_sessions = parse_event_sessions(data["event_url"])

        start_iso = None
        end_iso = None

        if parsed_sessions:
            valid_starts = [s.start_datetime_local for s in parsed_sessions if s.start_datetime_local]
            if valid_starts:
                start_iso = min(valid_starts)

            # end_date_local은 Race 세션의 시작 시간 + 2시간으로 고정
            race_session = next((s for s in parsed_sessions if s.session.upper() == "RACE"), None)
            if race_session and race_session.start_datetime_local:
                try:
                    race_start_dt = datetime.fromisoformat(race_session.start_datetime_local)
                    race_end_dt = race_start_dt + timedelta(hours=2)
                    end_iso = race_end_dt.isoformat()
                    # Race 세션 자체의 end_datetime_local 도 동일하게 + 2시간 적용
                    race_session.end_datetime_local = end_iso
                except ValueError:
                    pass

            # 계산에 실패했다면 기존 로직(가급적 마지막 끝나는 시간) 등으로 폴백
            if not end_iso:
                valid_ends = [s.end_datetime_local for s in parsed_sessions if s.end_datetime_local]
                if valid_ends:
                    end_iso = max(valid_ends)

        if not start_iso and start_date:
            start_iso = f"{start_date}T00:00:00"
        if not end_iso and end_date:
            end_iso = f"{end_date}T23:59:59"

        cancellation_reason = None
        if data.get("status") == "Cancelled":
            cancellation_reason = get_cancellation_reason(data["event_url"])

        events.append(
            EventItem(
                round=data["round"],
                status=data["status"],
                event_type=data["event_type"],
                title=data.get("location_title") or extract_location_from_title(data["title"]),
                country=data["country"],
                date_range_text=data["date_range_text"],
                start_date_local=start_iso,
                end_date_local=end_iso,
                event_url=data["event_url"],
                cancellation_reason=cancellation_reason,
                sessions=parsed_sessions,
            )
        )

    # 정렬
    def sort_key(event: EventItem):
        if event.round is None:
            return (0, event.start_date_local or "")
        return (1, event.round)

    events.sort(key=sort_key)
    return events


def calculate_standings(events: list[EventItem]) -> tuple[list[dict], list[dict]]:
    from collections import defaultdict
    driver_pts = defaultdict(float)
    driver_team = {}
    team_pts = defaultdict(float)

    for event in events:
        for session in event.sessions:
            if not session.results:
                continue
            for r in session.results:
                if r.pts:
                    try:
                        p = float(r.pts)
                    except ValueError:
                        continue
                    driver_pts[r.driver] += p
                    if r.team:
                        driver_team[r.driver] = r.team
                        team_pts[r.team] += p

    def format_pts(p: float) -> str:
        return str(int(p)) if p.is_integer() else str(p)

    driver_standings = [
        {"position": i + 1, "driver": d, "team": driver_team.get(d, ""), "points": format_pts(p)}
        for i, (d, p) in enumerate(sorted(driver_pts.items(), key=lambda x: x[1], reverse=True))
    ]

    team_standings = [
        {"position": i + 1, "team": t, "points": format_pts(p)}
        for i, (t, p) in enumerate(sorted(team_pts.items(), key=lambda x: x[1], reverse=True))
    ]

    return driver_standings, team_standings


def main():
    events = parse_calendar()
    
    driver_standings, team_standings = calculate_standings(events)

    output = {
        "season": 2026,
        "calendar_url": CALENDAR_URL,
        "datetime_format": "local ISO 8601 without timezone offset",
        "driver_standings": driver_standings,
        "team_standings": team_standings,
        "events": [
            {
                **{
                    k: v for k, v in asdict(event).items()
                    if k not in ("sessions",) and not (k == "cancellation_reason" and v is None)
                },
                "sessions": [
                    {
                        **{k: v for k, v in asdict(session).items() if k != "results"},
                        **({
                            "results": [
                                {k: v for k, v in asdict(r).items() if v is not None}
                                for r in session.results
                            ]
                           } if session.results else {})
                    }
                    for session in event.sessions
                ],
            }
            for event in events
        ],
    }

    with open("f1_2026_schedule_local_iso.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(events)} events to f1_2026_schedule_local_iso.json")


if __name__ == "__main__":
    main()