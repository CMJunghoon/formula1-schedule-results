"""
FastF1 API를 이용해 2026 F1 시즌 스케줄 및 결과를 수집하여
f1_2026_schedule_local_iso_fastf1.json 포맷으로 저장합니다.

기존 2026_F1_SC.py(웹 스크래핑)를 FastF1 API 기반으로 재구현한 버전입니다.
세션 시각은 SessionXDateUtc(UTC) 기준을 그대로 로컬 ISO 형식으로 출력합니다.
"""

import json
import math
import os
import re
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import fastf1
from firebase_manager import FirebaseManager

# ── 전역 플레이어 데이터 저장소 ──────────────────────────────────────────
# { "First_Last": { ...player info... } }
all_players_data = {}

# ── 캐시 설정 ─────────────────────────────────────────────────────────────────
CACHE_DIR = os.path.join(os.path.dirname(__file__), ".fastf1_cache")
os.makedirs(CACHE_DIR, exist_ok=True)
fastf1.Cache.enable_cache(CACHE_DIR)

SEASON = 2026
OUTPUT_FILE = "f1_2026_schedule_local_iso_fastf1.json"
CALENDAR_URL = f"https://www.formula1.com/en/racing/{SEASON}"

# FastF1 세션명 → 출력 세션명 매핑
SESSION_NAME_MAP = {
    "Practice 1": "Practice 1",
    "Practice 2": "Practice 2",
    "Practice 3": "Practice 3",
    "Sprint Qualifying": "Sprint Qualifying",
    "Sprint Shootout": "Sprint Qualifying",
    "Sprint": "Sprint",
    "Qualifying": "Qualifying",
    "Race": "Race",
}

# 세션 기본 지속 시간 (분)
SESSION_DURATION = {
    "Practice 1": 60, "Practice 2": 60, "Practice 3": 60,
    "Sprint Qualifying": 44, "Sprint Shootout": 44,
    "Sprint": 30,
    "Qualifying": 60,
    "Race": 120,
}

PRACTICE_SESSIONS   = {"Practice 1", "Practice 2", "Practice 3"}
QUALIFYING_SESSIONS = {"Qualifying", "Sprint Qualifying", "Sprint Shootout"}

# 취소된 라운드 정보 (RoundNumber 기준)
CANCELLED_ROUNDS = {4, 5}

# 취소 사유
CANCELLATION_REASON_RAW = (
    "After careful evaluations, due to the ongoing situation in the Middle East region, "
    "the Bahrain and Saudi Arabian Grands Prix will not take place in April. "
    "While several alternatives were considered, it was ultimately decided that no substitutions will be made in April. "
    "The Formula 2, Formula 3 and F1 ACADEMY rounds will also not take place during their scheduled times. "
    "The decision has been taken in full consultation with the FIA and respective promoters."
)

CANCELLATION_REASON_KR = (
    "중동 지역의 지속적인 상황으로 인해 신중한 검토 끝에, 바레인 및 사우디아라비아 그랑프리는 4월에 개최되지 않습니다. "
    "여러 대안이 검토되었으나 4월 중 대체 일정을 편성하지 않기로 최종 결정하였습니다. "
    "포뮬러 2, 포뮬러 3, F1 아카데미 라운드 또한 예정된 일정에 열리지 않습니다. "
    "이 결정은 FIA 및 각 프로모터와 충분한 협의를 거쳐 이루어졌습니다."
)


def fmt_dt(dt) -> Optional[str]:
    if dt is None: return None
    try:
        if pd.isna(dt): return None
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    except: return None


def td_to_laptime(td) -> str:
    if pd.isna(td) or td is None: return ""
    if hasattr(td, "total_seconds"):
        s = td.total_seconds()
        m = int(s // 60)
        ss = s - m * 60
        return f"{m}:{ss:06.3f}"
    return str(td)


def _safe_isnan(val) -> bool:
    try:
        if val is None: return True
        return math.isnan(float(val))
    except: return False


def get_session_results(ff1_session) -> Optional[list]:
    """FastF1 세션 객체에서 결과를 추출하여 dict 리스트로 반환."""
    try:
        sname = ff1_session.name  # FastF1 원래 이름
        is_practice = sname in PRACTICE_SESSIONS
        is_qualifying = sname in QUALIFYING_SESSIONS

        # 프랙티스 및 퀄리파잉은 랩타임/기록 수집을 위해 laps=True 권장 (특히 Sprint Qualifying)
        # 퀄리파잉 결과 계산에 Race Control Message가 필요할 수 있으므로 messages=is_qualifying 설정
        ff1_session.load(laps=(is_practice or is_qualifying), telemetry=False, weather=False, messages=is_qualifying)
        results_df = ff1_session.results
        if results_df is None or results_df.empty:
            return None

        out = []

        # 1) 프랙티스 세션: 랩타임 기반으로 순위 재계산 (결과 테이블에 시간이 없는 경우 대비)
        if is_practice:
            # 모든 드라이버의 가장 빠른 랩 추출
            best_laps_list = []
            for _, row in results_df.iterrows():
                abbr = row.get("Abbreviation")
                d_laps = ff1_session.laps.pick_driver(abbr)
                if not d_laps.empty:
                    fastest = d_laps.pick_fastest()
                    if fastest is not None and not pd.isna(fastest.get("LapTime")):
                        best_laps_list.append({
                            "driver": f"{row['FirstName']} {row['LastName']}".strip(),
                            "team": row.get("TeamName", ""),
                            "lap_time": fastest["LapTime"]
                        })
            
            # 랩타임 순으로 정렬
            best_laps_list.sort(key=lambda x: x["lap_time"])
            
            for i, entry in enumerate(best_laps_list, 1):
                out.append({
                    "pos": str(i),
                    "driver": entry["driver"],
                    "team": entry["team"],
                    "time_gap": td_to_laptime(entry["lap_time"])
                })
            
            # 선수 정보 수집 (프랙티스는 FirstName/LastName이 직접 결과에 없을 수 있으나 로직상 가능)
            # 하지만 상세 정보는 결과 테이블(results_df)에서 직접 가져오는 게 정확함
            for _, row in results_df.iterrows():
                fname = row.get("FirstName")
                lname = row.get("LastName")
                if pd.isna(fname) or pd.isna(lname): continue
                key = f"{fname}_{lname}"
                if key not in all_players_data:
                    all_players_data[key] = {
                        "firstname": fname,
                        "lastname": lname,
                        "shortname": row.get("Abbreviation", ""),
                        "team": row.get("TeamName", ""),
                        "team_color": f"#{row.get('TeamColor', 'FFFFFF')}",
                        "driver_number": str(row.get("Number", ""))
                    }

            return out if out else None

        # 2) 퀄리파잉 세션
        elif sname in QUALIFYING_SESSIONS:
            for _, row in results_df.iterrows():
                pos_raw = row.get("Position")
                pos = str(int(float(pos_raw))) if not _safe_isnan(pos_raw) else "NC"
                
                first = str(row.get("FirstName") or "").strip()
                last  = str(row.get("LastName") or "").strip()
                driver = f"{first} {last}".strip() if first or last else str(row.get("FullName", ""))
                
                out.append({
                    "pos": pos,
                    "driver": driver,
                    "team": str(row.get("TeamName") or ""),
                    "q1": td_to_laptime(row.get("Q1")),
                    "q2": td_to_laptime(row.get("Q2")),
                    "q3": td_to_laptime(row.get("Q3")),
                })

                # 선수 정보 수집
                fname = row.get("FirstName")
                lname = row.get("LastName")
                if not pd.isna(fname) and not pd.isna(lname):
                    key = f"{fname}_{lname}"
                    if key not in all_players_data:
                        all_players_data[key] = {
                            "firstname": fname,
                            "lastname": lname,
                            "shortname": row.get("Abbreviation", ""),
                            "team": row.get("TeamName", ""),
                            "team_color": f"#{row.get('TeamColor', 'FFFFFF')}",
                            "driver_number": str(row.get("Number", ""))
                        }
            return out if out else None

        # 3) 기타 (Race, Sprint)
        else:
            for _, row in results_df.iterrows():
                pos_raw = row.get("Position")
                pos = str(int(float(pos_raw))) if not _safe_isnan(pos_raw) else "NC"
                
                first = str(row.get("FirstName") or "").strip()
                last  = str(row.get("LastName") or "").strip()
                driver = f"{first} {last}".strip() if first or last else str(row.get("FullName", ""))
                
                pts_raw = row.get("Points", 0)
                try: pts_str = str(int(float(pts_raw))) if not _safe_isnan(pts_raw) else "0"
                except: pts_str = str(pts_raw)
                team = str(row.get("TeamName") or "")
                out.append({"pos": pos, "driver": driver, "team": team, "pts": pts_str})

                # 선수 정보 수집
                fname = row.get("FirstName")
                lname = row.get("LastName")
                if not pd.isna(fname) and not pd.isna(lname):
                    key = f"{fname}_{lname}"
                    if key not in all_players_data:
                        all_players_data[key] = {
                            "firstname": fname,
                            "lastname": lname,
                            "shortname": row.get("Abbreviation", ""),
                            "team": row.get("TeamName", ""),
                            "team_color": f"#{row.get('TeamColor', 'FFFFFF')}",
                            "driver_number": str(row.get("Number", ""))
                        }
        return out if out else None
    except: return None


def build_date_range_text(start_dt, end_dt) -> str:
    if start_dt is None or end_dt is None: return ""
    if start_dt.month == end_dt.month:
        return f"{start_dt.day:02d} - {end_dt.day:02d} {start_dt.strftime('%b').upper()}"
    return f"{start_dt.day:02d} {start_dt.strftime('%b').upper()} - {end_dt.day:02d} {end_dt.strftime('%b').upper()}"


def calculate_standings(events: list) -> tuple[list[dict], list[dict]]:
    from collections import defaultdict
    driver_pts = defaultdict(float)
    driver_team = {}
    team_pts = defaultdict(float)

    for event in events:
        for session in event.get("sessions", []):
            if not session.get("results"): continue
            for r in session["results"]:
                if r.get("pts"):
                    try: p = float(r["pts"])
                    except: continue
                    driver_pts[r["driver"]] += p
                    if r.get("team"):
                        driver_team[r["driver"]] = r["team"]
                        team_pts[r["team"]] += p

    def format_pts(p: float) -> str:
        return str(int(p)) if p.is_integer() else str(p)

    d_standings = []
    sorted_drivers = sorted(driver_pts.items(), key=lambda x: x[1], reverse=True)
    for i, (name, pts) in enumerate(sorted_drivers, 1):
        if pts == 0 and not driver_team.get(name): continue
        d_standings.append({"position": i, "driver": name, "team": driver_team.get(name, ""), "points": format_pts(pts)})

    t_standings = []
    sorted_teams = sorted(team_pts.items(), key=lambda x: x[1], reverse=True)
    for i, (name, pts) in enumerate(sorted_teams, 1):
        if pts == 0: continue
        t_standings.append({"position": i, "team": name, "points": format_pts(pts)})

    return d_standings, t_standings


def parse_all_events() -> list:
    print(f"[INFO] FastF1 {SEASON} 시즌 캘린더 로드 중...")
    schedule = fastf1.get_event_schedule(SEASON, include_testing=True)
    from datetime import timezone
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    events_out = []
    seen_urls = set()

    for _, event_row in schedule.iterrows():
        round_no = event_row.get("RoundNumber")
        event_name = str(event_row.get("EventName", "")).strip()
        country = str(event_row.get("Country", "")).strip()
        location = str(event_row.get("Location", "")).strip()

        is_testing = str(round_no) == "0" or "testing" in event_name.lower() or "pre-season" in event_name.lower()
        event_type = "testing" if is_testing else "grand_prix"

        status = "Scheduled"
        c_reason = None
        c_reason_kr = None
        if round_no in CANCELLED_ROUNDS:
            status = "Cancelled"
            c_reason = CANCELLATION_REASON_RAW
            c_reason_kr = CANCELLATION_REASON_KR

        display_title = country if not is_testing else event_name
        if not display_title: display_title = location

        sessions_out = []
        first_start, last_end, race_end = None, None, None

        if status != "Cancelled":
            for i in range(1, 6):
                s_name_raw = event_row.get(f"Session{i}")
                s_date_utc = event_row.get(f"Session{i}DateUtc")
                if not s_name_raw or pd.isna(s_name_raw) or pd.isna(s_date_utc): continue
                
                s_name_raw = str(s_name_raw).strip()
                session_display = SESSION_NAME_MAP.get(s_name_raw, s_name_raw)

                try:
                    start_dt = pd.Timestamp(s_date_utc).to_pydatetime().replace(tzinfo=None)
                    dur_min = SESSION_DURATION.get(s_name_raw, 60)
                    end_dt = start_dt + timedelta(minutes=dur_min)
                except: continue

                if first_start is None or start_dt < first_start: first_start = start_dt
                if last_end is None or end_dt > last_end: last_end = end_dt

                session_results = None
                if not is_testing and start_dt < now_utc:
                    try:
                        print(f"  → [{event_name}] {session_display} 결과 로드...")
                        ff1_session = fastf1.get_session(SEASON, int(round_no), s_name_raw)
                        session_results = get_session_results(ff1_session)
                    except Exception as e:
                        print(f"    [WARN] 로드 실패: {e}")

                if session_display == "Race": race_end = end_dt

                session_obj = {
                    "session": session_display,
                    "start_datetime_local": fmt_dt(start_dt),
                    "end_datetime_local": fmt_dt(end_dt),
                }
                if session_results: session_obj["results"] = session_results
                sessions_out.append(session_obj)

        slug = location.lower().replace(" ", "-").replace("_", "-") if location else country.lower()
        event_url = f"https://www.formula1.com/en/racing/{SEASON}/{slug}" if not is_testing else f"https://www.formula1.com/en/racing/{SEASON}/pre-season-testing"
        if event_url in seen_urls: continue
        seen_urls.add(event_url)

        event_start = fmt_dt(first_start)
        event_end = fmt_dt(race_end) if race_end else fmt_dt(last_end)
        if not event_start:
            ed = event_row.get("EventDate")
            if not pd.isna(ed):
                try: event_start = fmt_dt(pd.Timestamp(ed).to_pydatetime().replace(tzinfo=None))
                except: pass

        evt = {
            "round": int(round_no) if not is_testing else None,
            "status": status,
            "event_type": event_type,
            "title": display_title,
            "country": country,
            "date_range_text": build_date_range_text(first_start, last_end),
            "start_date_local": event_start,
            "end_date_local": event_end,
            "event_url": event_url,
        }
        if c_reason: evt["cancellation_reason"] = c_reason
        if c_reason_kr: evt["cancellation_reason_kr"] = c_reason_kr
        evt["sessions"] = sessions_out
        events_out.append(evt)
        print(f"  [OK] {display_title} (Round {evt['round']})")

    return events_out


def main():
    events = parse_all_events()
    d_standings, t_standings = calculate_standings(events)

    output = {
        "season": SEASON,
        "calendar_url": CALENDAR_URL,
        "datetime_format": "local ISO 8601 without timezone offset",
        "driver_standings": d_standings,
        "team_standings": t_standings,
        "events": events,
    }

    out_file = "f1_2026_schedule_local_iso_fastf1.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ {len(events)}개 이벤트를 {out_file}에 저장했습니다.")

    # ── Firestore 업로드 ──
    try:
        print("\n[INFO] Firestore 업로드 시작...")
        fm = FirebaseManager()
        
        # 1. 선수 정보 업로드
        if all_players_data:
            fm.upload_players(list(all_players_data.values()))
        
        # 2. 순위 정보 업로드
        fm.upload_standings(SEASON, d_standings, t_standings)
        
        # 3. 이벤트 및 세션 정보 업로드
        fm.upload_events(events)
        
        print("\n🚀 Firestore 업로드 작업이 모두 완료되었습니다.")
    except Exception as e:
        print(f"\n❌ Firestore 업로드 중 오류 발생: {e}")
        print("참고: 'serviceAccountKey.json' 파일이 프로젝트 루트에 필요합니다.")


if __name__ == "__main__":
    main()
