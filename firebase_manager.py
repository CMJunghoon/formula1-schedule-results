import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import os

class FirebaseManager:
    def __init__(self, service_account_path='serviceAccountKey.json'):
        """
        Firebase Admin SDK 초기화
        :param service_account_path: 서비스 계정 키 파일 경로
        """
        if not firebase_admin._apps:
            if os.path.exists(service_account_path):
                cred = credentials.Certificate(service_account_path)
                firebase_admin.initialize_app(cred)
            else:
                print(f"[ERROR] Firebase 서비스 계정 키 파일을 찾을 수 없습니다: {service_account_path}")
                print("구글 클라우드 콘솔에서 서비스 계정 키를 다운로드하여 'serviceAccountKey.json'으로 저장하세요.")
                raise FileNotFoundError(f"Missing {service_account_path}")
        
        self.db = firestore.client()

    def upload_players(self, players):
        """
        선수 정보 업로드 (Players 컬렉션)
        :param players: 선수 정보 리스트 [dict, ...]
        """
        print(f"[INFO] {len(players)}명의 선수 정보 업로드 중...")
        batch = self.db.batch()
        for p in players:
            # Document ID: firstname_lastname (소문자)
            doc_id = f"{p['firstname'].lower()}_{p['lastname'].lower()}".replace(" ", "_")
            doc_ref = self.db.collection('Players').document(doc_id)
            batch.set(doc_ref, p)
        batch.commit()
        print("[OK] 선수 정보 업로드 완료")

    def upload_standings(self, season, driver_standings, team_standings):
        """
        순위 정보 업로드 (Results, TeamResults 컬렉션)
        """
        print(f"[INFO] {season} 시즌 순위 정보 업로드 중...")
        
        # Driver Standings
        driver_ref = self.db.collection('Results').document(f'driver_standings_{season}')
        driver_ref.set({
            'season': season,
            'last_updated': datetime.now().isoformat(),
            'standings': driver_standings
        })
        
        # Team Standings
        team_ref = self.db.collection('TeamResults').document(f'team_standings_{season}')
        team_ref.set({
            'season': season,
            'last_updated': datetime.now().isoformat(),
            'standings': team_standings
        })
        print("[OK] 순위 정보 업로드 완료")

    def upload_events(self, events):
        """
        이벤트 및 세션 정보 업로드 (Events 컬렉션 및 하위 sessions 컬렉션)
        :param events: 이벤트 정보 리스트 (세션 결과 포함)
        """
        print(f"[INFO] {len(events)}개의 이벤트 정보 업로드 중...")
        for event in events:
            # Round ID: round_01, round_02 ... (Testing은 testing_번호)
            if event['round'] is not None:
                doc_id = f"round_{int(event['round']):02d}"
            else:
                # Testing 등의 경우 타이틀 기반 ID 생성
                doc_id = f"event_{event['title'].lower().replace(' ', '_')}"
            
            event_ref = self.db.collection('Events').document(doc_id)
            
            # 이벤트 기본 필드 (sessions 제외)
            event_data = {k: v for k, v in event.items() if k != 'sessions'}
            event_ref.set(event_data)
            
            # 하위 sessions 컬렉션 업로드
            sessions = event.get('sessions', [])
            for session in sessions:
                # Session ID: session_name (소문자, 공백은 언더바로)
                s_name = session['session'].lower().replace(' ', '_')
                session_ref = event_ref.collection('sessions').document(s_name)
                session_ref.set(session)
                
        print("[OK] 이벤트 및 세션 정보 업로드 완료")

if __name__ == "__main__":
    # 간단한 연동 테스트용 (키 파일이 있을 경우에만 작동)
    try:
        fm = FirebaseManager()
        print("Firebase 연결 성공")
    except Exception as e:
        print(f"Firebase 연결 실패: {e}")
