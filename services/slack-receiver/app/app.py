import os
import json
import base64
import zlib
import requests
import threading  
from flask import Flask, request, jsonify

app = Flask(__name__)

# ==========================================
# 환경변수 설정
# ==========================================
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER = os.getenv("GITHUB_OWNER")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_REF = os.getenv("GITHUB_REF", "jy")
ACTIVATE_SANDBOX_WORKFLOW_FILE = os.getenv("ACTIVATE_SANDBOX_WORKFLOW_FILE", "activate-sandbox.yaml")
CREATE_CASE_BRANCH_WORKFLOW_FILE = os.getenv("CREATE_CASE_BRANCH_WORKFLOW_FILE", "create-case-branch.yaml")

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok"}), 200

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
            print(f"✅ [SUCCESS] Triggered {workflow_file} successfully!", flush=True)
            return True
        else:
            print(f"❌ [ERROR] GitHub dispatch failed for {workflow_file}: {resp.status_code} - {resp.text}", flush=True)
            return False
    except Exception as e:
        print(f"❌ [EXCEPTION] Failed to communicate with GitHub: {e}", flush=True)
        return False


def process_approval_task(compressed_value, user_id, username, response_url):
    print(f"⚙️ [BACKGROUND] {username}님의 요청을 백그라운드에서 처리 시작...", flush=True)
    
    missing_vars = [var_name for var_name, var_val in [
        ("GITHUB_TOKEN", GITHUB_TOKEN), ("GITHUB_OWNER", GITHUB_OWNER), 
        ("GITHUB_REPO", GITHUB_REPO), ("GITHUB_REF", GITHUB_REF)
    ] if not var_val]

    if missing_vars:
        error_msg = f"❌ 서버 설정 에러: 환경변수 {', '.join(missing_vars)} 가 누락되었습니다."
        print(error_msg, flush=True)
        requests.post(response_url, json={"replace_original": True, "text": error_msg})
        return

    try:
        decompressed_bytes = zlib.decompress(base64.b64decode(compressed_value))
        combined_payload = json.loads(decompressed_bytes.decode('utf-8'))
        
        sandbox_spec = combined_payload.get("spec", {})
        failure_artifact = combined_payload.get("failure_artifact", {})
        normal_artifact = combined_payload.get("normal_artifact", {})
        
        case_id = sandbox_spec.get("metadata", {}).get("case_id", "unknown")
        source_service = sandbox_spec.get("metadata", {}).get("source_service", "unknown")
        sandbox_manifest_path = sandbox_spec.get("metadata", {}).get("sandbox_manifest_path", "")
        consumer_image_ref = sandbox_spec.get("sandbox", {}).get("consumer_image_ref", "")

        print(f"📦 [DATA] Payload decompressed successfully. Case ID: {case_id}", flush=True)

        sandbox_success = github_dispatch(
            ACTIVATE_SANDBOX_WORKFLOW_FILE,
            {
                "spec_json": json.dumps(sandbox_spec, ensure_ascii=False),
                "failure_artifact_json": json.dumps(failure_artifact, ensure_ascii=False),
                "normal_artifact_json": json.dumps(normal_artifact, ensure_ascii=False),
            }
        )

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
            requests.post(response_url, json={"replace_original": True, "blocks": success_blocks})
            print("💬 [SLACK] 슬랙 UI 업데이트 성공!", flush=True)
        else:
            requests.post(response_url, json={"replace_original": True, "text": "❌ 깃허브 액션 실행 중 실패가 발생했습니다. 서버 로그를 확인해주세요."})

    except Exception as e:
        print(f"❌ [ERROR] Processing failed: {e}", flush=True)
        requests.post(response_url, json={"replace_original": True, "text": f"❌ 데이터 처리 중 에러 발생: {e}"})


@app.route('/slack/actions', methods=['POST'])
def slack_actions():
    payload_str = request.form.get('payload')
    if not payload_str:
        return "No payload", 400
        
    slack_payload = json.loads(payload_str)

    if slack_payload.get('type') == 'block_actions':
        actions = slack_payload.get('actions', [])
        if not actions:
            return "No actions", 400
            
        action = actions[0]
        action_id = action.get('action_id')
        compressed_value = action.get('value')
        
        response_url = slack_payload.get('response_url') 
        
        user_id = slack_payload.get('user', {}).get('id')
        username = slack_payload.get('user', {}).get('username', '지휘관')

        if action_id == "approve_sandbox_creation" and compressed_value and response_url:
            print(f"🚨 [SLACK_RECV] Action ID: {action_id} clicked by user: {username}", flush=True)
            thread = threading.Thread(target=process_approval_task, args=(compressed_value, user_id, username, response_url))
            thread.start()
            
            return "", 200 

    return "", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)