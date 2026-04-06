import os
import json
import base64
import zlib
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ==========================================
# ⚙️ 환경변수 설정 (GitHub Actions 트리거용)
# ==========================================
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER = os.getenv("GITHUB_OWNER")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_REF = os.getenv("GITHUB_REF", "jy")
ACTIVATE_SANDBOX_WORKFLOW_FILE = os.getenv("ACTIVATE_SANDBOX_WORKFLOW_FILE", "activate-sandbox.yaml")
CREATE_CASE_BRANCH_WORKFLOW_FILE = os.getenv("CREATE_CASE_BRANCH_WORKFLOW_FILE", "create-case-branch.yaml")

# 🩺 ALB 타겟 그룹 헬스체크용 엔드포인트
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok"}), 200

# 🎯 GitHub Actions 공통 트리거 함수
def github_dispatch(workflow_file: str, inputs: dict) -> bool:
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/{workflow_file}/dispatches"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {"ref": GITHUB_REF, "inputs": inputs}
    
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        if resp.status_code in (201, 204):
            print(f"✅ [SUCCESS] Triggered {workflow_file} successfully!")
            return True
        else:
            print(f"❌ [ERROR] GitHub dispatch failed for {workflow_file}: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        print(f"❌ [EXCEPTION] Failed to communicate with GitHub: {e}")
        return False


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

    # Block Actions (버튼 클릭) 처리
    if slack_payload.get('type') == 'block_actions':
        actions = slack_payload.get('actions', [])
        if not actions:
            return jsonify({"error": "No actions found"}), 400
            
        action = actions[0]
        action_id = action.get('action_id')
        compressed_value = action.get('value')
        
        # 슬랙 유저 정보 추출 (승인자 멘션용)
        user_id = slack_payload.get('user', {}).get('id')
        username = slack_payload.get('user', {}).get('username', '지휘관')

        print(f"🚨 [SLACK_RECV] Action ID: {action_id} clicked by user: {username} ({user_id})")

        # 🎯 "approve_sandbox_creation" 버튼인지 확인
        if action_id == "approve_sandbox_creation" and compressed_value:
            
            # 1. 환경변수 누락 체크
            missing_vars = [var_name for var_name, var_val in [
                ("GITHUB_TOKEN", GITHUB_TOKEN), ("GITHUB_OWNER", GITHUB_OWNER), 
                ("GITHUB_REPO", GITHUB_REPO), ("GITHUB_REF", GITHUB_REF)
            ] if not var_val]

            if missing_vars:
                error_msg = f"❌ 서버 설정 에러: 환경변수 {', '.join(missing_vars)} 가 누락되었습니다."
                print(error_msg)
                # 에러 시 원래 슬랙 메시지는 유지하고, 에러 메시지를 반환
                return jsonify({"text": error_msg}), 200

            try:
                # 2. Base64 디코딩 및 zlib 압축 해제 (notifier 코드와 쌍을 이룸)
                decompressed_bytes = zlib.decompress(base64.b64decode(compressed_value))
                combined_payload = json.loads(decompressed_bytes.decode('utf-8'))
                
                sandbox_spec = combined_payload.get("spec", {})
                failure_artifact = combined_payload.get("failure_artifact", {})
                normal_artifact = combined_payload.get("normal_artifact", {})
                
                case_id = sandbox_spec.get("metadata", {}).get("case_id", "unknown")
                source_service = sandbox_spec.get("metadata", {}).get("source_service", "unknown")
                sandbox_manifest_path = sandbox_spec.get("metadata", {}).get("sandbox_manifest_path", "")
                consumer_image_ref = sandbox_spec.get("sandbox", {}).get("consumer_image_ref", "")

                print(f"📦 [DATA] Successfully decompressed payload for Case ID: {case_id}")

                # 3. GitHub Actions 격발 (1연사: 샌드박스 배포)
                sandbox_success = github_dispatch(
                    ACTIVATE_SANDBOX_WORKFLOW_FILE,
                    {
                        "spec_json": json.dumps(sandbox_spec, ensure_ascii=False),
                        "failure_artifact_json": json.dumps(failure_artifact, ensure_ascii=False),
                        "normal_artifact_json": json.dumps(normal_artifact, ensure_ascii=False),
                    }
                )

                # 4. GitHub Actions 격발 (2연사: 케이스 브랜치 생성)
                branch_success = github_dispatch(
                    CREATE_CASE_BRANCH_WORKFLOW_FILE,
                    {
                        "case_id": case_id,
                        "service": source_service,
                        "base_ref": GITHUB_REF,
                        "source_image_ref": consumer_image_ref,
                        "sandbox_manifest_path": sandbox_manifest_path,
                        "note": f"Case branch created via Slack HITL approval by {username}",
                    }
                )

                # 5. 슬랙 응답: 버튼 메시지를 '승인 완료' 메시지로 교체 (중복 클릭 방지 및 시각적 피드백)
                if sandbox_success and branch_success:
                    success_blocks = [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"✅ *포렌식 샌드박스 배포 승인 완료!*\n<@{user_id}>님의 승인으로 `{case_id}` (서비스: `{source_service}`) 분석용 파이프라인 가동을 시작했습니다. 🚀"
                            }
                        }
                    ]
                    return jsonify({
                        "replace_original": True,
                        "blocks": success_blocks
                    }), 200
                else:
                    return jsonify({"text": "❌ 깃허브 액션 실행 중 일부 실패가 발생했습니다. 서버 로그를 확인해주세요."}), 200

            except Exception as e:
                print(f"❌ [ERROR] Failed to process sandbox approval: {e}")
                return jsonify({"text": f"❌ 데이터 압축 해제 또는 통신 중 예외가 발생했습니다: {e}"}), 200

    return jsonify({"text": "알 수 없는 액션이거나 승인 버튼이 아닙니다."}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)