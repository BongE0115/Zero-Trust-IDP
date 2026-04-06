# 트리거 4
import os
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- [환경변수에서 설정값 읽어오기 (하드코딩 100% 제거!)] ---
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER = os.getenv("GITHUB_OWNER")
GITHUB_REPO = os.getenv("GITHUB_REPO")
WORKFLOW_FILE = os.getenv("WORKFLOW_FILE")
GITHUB_REF = os.getenv("GITHUB_REF")

# 🩺 ALB 타겟 그룹 헬스체크용 엔드포인트
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok"}), 200

# 🚀 슬랙 버튼 클릭 수신 엔드포인트
@app.route('/slack/actions', methods=['POST'])
def slack_actions():
    payload_str = request.form.get('payload')
    if not payload_str:
        return jsonify({"error": "No payload provided"}), 400
        
    try:
        slack_payload = json.loads(payload_str)
    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON payload"}), 400

    if slack_payload.get('type') in ['block_actions', 'interactive_message']:
        actions = slack_payload.get('actions', [])
        if not actions:
            return jsonify({"error": "No actions found"}), 400
            
        action_value_str = actions[0].get('value')
        if not action_value_str:
            return jsonify({"error": "No value in action"}), 400

        try:
            data = json.loads(action_value_str)
        except json.JSONDecodeError:
            return jsonify({"error": "Invalid JSON in action value"}), 400

        username = slack_payload.get('user', {}).get('username', '지휘관')
        print(f"🚨 [SLACK COMMAND] 샌드박스 기동 명령 수신! 요청자: {username}")

        # 🚨 [필수 환경변수 누락 체크]
        missing_vars = []
        if not GITHUB_TOKEN: missing_vars.append("GITHUB_TOKEN")
        if not GITHUB_OWNER: missing_vars.append("GITHUB_OWNER")
        if not GITHUB_REPO: missing_vars.append("GITHUB_REPO")
        if not WORKFLOW_FILE: missing_vars.append("WORKFLOW_FILE")
        if not GITHUB_REF: missing_vars.append("GITHUB_REF")

        if missing_vars:
            error_msg = f"❌ 서버 설정 에러: 환경변수 {', '.join(missing_vars)} 가 누락되었습니다."
            print(error_msg)
            return jsonify({"text": error_msg}), 200

        # 3. 깃허브 액션 격발
        url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/{WORKFLOW_FILE}/dispatches"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        
        gh_payload = {
            "ref": GITHUB_REF,
            "inputs": {
                "spec_json": json.dumps(data.get("spec", {}), ensure_ascii=False),
                "failure_artifact_json": json.dumps(data.get("failure_artifact", {}), ensure_ascii=False),
                "normal_artifact_json": json.dumps(data.get("normal_artifact", {}), ensure_ascii=False)
            }
        }

        try:
            resp = requests.post(url, headers=headers, json=gh_payload)
            
            if resp.status_code in (201, 204):
                print(f"✅ [SUCCESS] 깃허브 액션 트리거 성공! (상태 코드: {resp.status_code})")
                return jsonify({
                    "replace_original": True,
                    "text": f"✅ *배포 승인 완료!*\n요청자 `{username}`님의 승인으로 `{WORKFLOW_FILE}` 파이프라인 가동을 시작했습니다. 🚀"
                }), 200
            else:
                print(f"❌ [ERROR] 깃허브 액션 트리거 실패: {resp.status_code} - {resp.text}")
                return jsonify({"text": f"❌ 깃허브 액션 실행 실패 (상태 코드: {resp.status_code})"}), 200
                
        except Exception as e:
            print(f"❌ [ERROR] 깃허브 통신 중 예외 발생: {e}")
            return jsonify({"text": f"❌ 깃허브 서버와 통신할 수 없습니다: {e}"}), 200

    return jsonify({"text": "알 수 없는 액션입니다."}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)