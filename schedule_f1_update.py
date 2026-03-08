#!/usr/bin/env python3
"""
F1 세션 종료 30분 후 자동으로 2026_F1_SC.py를 실행하는 스케줄러.
- f1_2026_schedule_local_iso.json 에서 세션 end_datetime_local 을 읽음
- 현재 시각 기준 다음 "종료 + 30분" 시점을 찾아 대기
- 실행 완료 후 다음 세션으로 이동

사용법:
  python3 schedule_f1_update.py            # 일반 실행 (포그라운드)
  python3 schedule_f1_update.py &          # 백그라운드 실행
  nohup python3 schedule_f1_update.py &   # 터미널 종료 후에도 유지
"""

import json
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# --- 설정 ---
SCRIPT_DIR    = Path(__file__).parent
JSON_PATH     = SCRIPT_DIR / "f1_2026_schedule_local_iso.json"
MAIN_SCRIPT   = SCRIPT_DIR / "2026_F1_SC.py"
DELAY_MINUTES = 30          # 세션 종료 후 대기 시간(분)
# 한국 시간(KST, UTC+9)을 기준으로 동작. 필요 시 변경
LOCAL_TZ = ZoneInfo("Asia/Seoul")


def get_trigger_times(json_path: Path) -> list[datetime]:
    """JSON에서 모든 세션의 (end_datetime_local + 30분) 목록 반환 (오름차순)."""
    data = json.loads(json_path.read_text(encoding="utf-8"))
    triggers: list[datetime] = []

    for event in data.get("events", []):
        for session in event.get("sessions", []):
            end_str = session.get("end_datetime_local")
            if not end_str:
                continue
            try:
                # ISO 로컬 시간 파싱 (타임존 없음 → LOCAL_TZ 적용)
                end_local = datetime.fromisoformat(end_str).replace(tzinfo=LOCAL_TZ)
                trigger = end_local + timedelta(minutes=DELAY_MINUTES)
                label = f"{event.get('title','?')} / {session.get('session','?')}"
                triggers.append((trigger, label))
            except ValueError:
                pass

    triggers.sort(key=lambda x: x[0])
    return triggers


def run_main_script():
    """2026_F1_SC.py 실행."""
    print(f"[{now()}] ▶ 2026_F1_SC.py 실행 중...")
    result = subprocess.run(
        ["python3", str(MAIN_SCRIPT)],
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print("[STDERR]", result.stderr.strip())
    print(f"[{now()}] ✅ 실행 완료 (exit code: {result.returncode})")


def now() -> str:
    return datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")


def main():
    print(f"[{now()}] 🏁 F1 자동 업데이트 스케줄러 시작")
    print(f"      JSON  : {JSON_PATH}")
    print(f"      스크립트: {MAIN_SCRIPT}")
    print(f"      대기   : 세션 종료 후 {DELAY_MINUTES}분\n")

    while True:
        # JSON 을 매 루프마다 새로 읽어서 최신 일정 반영
        triggers = get_trigger_times(JSON_PATH)
        now_dt = datetime.now(LOCAL_TZ)

        # 아직 도래하지 않은 가장 가까운 트리거 찾기
        upcoming = [(t, label) for t, label in triggers if t > now_dt]

        if not upcoming:
            print(f"[{now()}] ⏹ 더 이상 예정된 세션이 없습니다. 스케줄러를 종료합니다.")
            break

        next_trigger, next_label = upcoming[0]
        wait_secs = (next_trigger - now_dt).total_seconds()

        print(f"[{now()}] ⏳ 다음 실행 예정:")
        print(f"      세션  : {next_label}")
        print(f"      시각  : {next_trigger.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"      대기  : {int(wait_secs // 3600)}시간 "
              f"{int((wait_secs % 3600) // 60)}분 {int(wait_secs % 60)}초\n")

        # 남은 시간 대기 (60초 간격으로 쪼개어 Ctrl+C 인터럽트 대응)
        while True:
            now_dt = datetime.now(LOCAL_TZ)
            remaining = (next_trigger - now_dt).total_seconds()
            if remaining <= 0:
                break
            sleep_chunk = min(remaining, 60)
            time.sleep(sleep_chunk)

        run_main_script()
        print()  # 줄바꿈 후 다음 루프


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n[{now()}] ⛔ 스케줄러가 사용자에 의해 중단되었습니다.")
