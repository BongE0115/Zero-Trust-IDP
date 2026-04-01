# slack trigger 발생 시 git actions

이 시스템은 크게 **[메시지 큐(Kafka)] ➔ [작업자(Worker)] ➔ [감시자(DLQ)] ➔ [API 서버] ➔ [외부 터널(Ngrok)]** 로 이어지는 유기적인 구조입니다.

자, 터미널 5개를 쫙 띄워놓고 지휘관 모드로 세팅을 시작해 보겠습니다!

---

### **🖥️ 터미널 1: Kafka 실행 (메시지 브로커 / 우체국)**

이 터미널은 모든 데이터가 오고 가는 중앙 우체국(Kafka)을 띄워두는 곳입니다. 보통 Docker를 이용해 백그라운드에서 실행합니다. (이미 켜져 있다면 이 터미널은 눈으로만 확인하고 넘어가셔도 됩니다.)

`# Kafka가 있는 디렉토리로 이동 (Docker Compose 파일이 있는 곳)
cd ~/hs

# Kafka 컨테이너 실행
docker-compose up -d`

- **동작 원리:** Kafka라는 거대한 메시지 큐 시스템이 `9092` 포트를 열고 대기합니다. 앞으로 모든 터미널(서버)들은 서로 직접 통신하지 않고, 오직 이 Kafka에 메시지를 던지고(Produce) 가져가는(Consume) 방식으로만 소통합니다.
    

---

### **🖥️ 터미널 2: Worker Consumer (작업자 / 피해자)**

실제로 들어온 '주문(Order)'을 처리하는 실무자입니다. 이번 시나리오에서는 '독이 든 사과(실패 요청)'를 먹고 에러를 뿜어내는 역할을 합니다.

`cd ~/hs/services/worker-consumer

# Kafka 주소 세팅
export KAFKA_BOOTSTRAP="127.0.0.1:9092"

# 실행!
python app/consumer.py`

- **동작 원리:**
    1. 켜지자마자 Kafka의 `orders`라는 우체통(토픽)을 계속 쳐다보고 있습니다.
    2. 주문이 들어오면 처리를 시도하다가, `should_fail=True`라는 값을 보면 고의로 **`ValueError`*를 발생시킵니다.
    3. 에러가 난 주문 데이터를 버리지 않고, Kafka의 **`orders-dlq` (Dead Letter Queue, 에러 보관함)** 이라는 격리된 우체통으로 던져버립니다.
        

---

### **🖥️ 터미널 3: DLQ Handler (감시 경찰 / 슬랙 알림 요원)**

에러 보관함(`orders-dlq`)만 전문적으로 감시하다가, 문제가 생기면 즉시 슬랙으로 경고를 때리는 경찰 역할입니다.

Bash

`cd ~/hs/services/dlq-handler

# 환경변수 세팅 (본인의 진짜 토큰을 넣으세요!)
export KAFKA_BOOTSTRAP="127.0.0.1:9092"
export SLACK_BOT_TOKEN="xoxb-사용자님의-슬랙-봇-토큰"
export SLACK_CHANNEL="C0AMPLBHE8Z"

# 실행!
python app/handler.py`

- **동작 원리:**
    - Kafka의 `orders-dlq` 우체통을 매의 눈으로 감시합니다.
    - 에러 데이터가 들어오면, 에러 종류와 내용을 분석해서 예쁜 Slack Block Kit (UI 카드) 형태로 조립합니다.
    - 이때 훗날 샌드박스를 만들 때 필요한 설계도(Payload)를 압축(zlib)하고 문자(Base64)로 변환해서 **[Create Sandbox]** 버튼 속에 몰래 숨겨 넣습니다.
    - 조립이 완료되면 슬랙 API를 호출해 사용자님의 채널로 카드를 쏩니다.
 
  
---

### **🖥️ 터미널 4: Producer API (지휘 통제실 웹 서버 / GitHub 격발기)**

브라우저에서 주문을 넣을 수 있는 화면을 제공하고, 훗날 슬랙 버튼을 눌렀을 때 그 신호를 받아 GitHub에 명령을 내리는 핵심 서버입니다.

Bash

`cd ~/hs/services/producer-api

# 환경변수 세팅 (본인의 진짜 토큰을 넣으세요!)
export KAFKA_BOOTSTRAP="127.0.0.1:9092"
export GITHUB_TOKEN="ghp_사용자님의-깃허브-토큰"

# 웹 서버 실행!
uvicorn app.app:app --host 0.0.0.0 --port 8081`

- **동작 원리:**
    - `http://localhost:8081` 로 접속하면 POC UI 화면(HTML)을 띄워줍니다.
    - 화면에서 **[실패 요청 보내기]**를 누르면, 그 데이터를 Kafka의 `orders` 토픽으로 던집니다. (이게 터미널 2번으로 흘러가는 시작점입니다.)
    - `POST /slack/interactive` 라는 특별한 뒷문을 열어두고 대기합니다. 이 뒷문은 슬랙 버튼 신호가 들어오면 압축된 데이터를 풀고 깃허브로 `workflow_dispatch` API를 쏘는 역할을 합니다.

---

### **🖥️ 터미널 5: Ngrok (외부 통신 터널)**

슬랙(미국 어딘가의 서버)이 내 노트북(localhost)에 있는 터미널 4번(8081 포트)으로 신호를 보낼 수 있도록 인터넷 터널을 뚫어줍니다.

Bash

`# 위치 상관없음
ngrok http 8081`

- **동작 원리:** `https://어쩌구저쩌구.ngrok-free.dev` 라는 공인 URL을 하나 만들어줍니다. 이 주소를 슬랙 설정(Interactivity Request URL)에 등록해 두었기 때문에, 슬랙에서 버튼을 누르면 이 주소를 타고 내 노트북의 `localhost:8081/slack/interactive` 로 정확히 배달됩니다.
    

---

### **🚀 전체 동작 시나리오 (복습)**

5개의 터미널이 모두 켜졌다면 아래 순서대로 동작하게 됩니다!

1. **브라우저**에서 `localhost:8081` 접속 ➔ **[실패 요청 보내기]** 클릭 **(터미널 4 ➔ 터미널 1)**
2. **터미널 2**가 에러를 뿜으며 `orders-dlq` 로 메시지 던짐 **(터미널 2 ➔ 터미널 1)**
3. **터미널 3**이 그걸 주워서 Slack 채널로 알람과 버튼을 전송 **(터미널 1 ➔ 터미널 3 ➔ Slack)**
4. 사용자가 Slack에서 **[Create Sandbox]** 버튼 클릭
5. Slack 서버가 **터미널 5(Ngrok)** 를 거쳐 **터미널 4**로 신호를 보냄 **(Slack ➔ 터미널 5 ➔ 터미널 4)**
6. **터미널 4**가 신호를 해석하고 GitHub API를 호출하여 Actions 실행! **(터미널 4 ➔ GitHub)**

자, 이제 이 흐름을 머릿속에 담고 다시 한번 처음부터 런칭해 보세요! 막힘없이 돌아가는 로그를 보면 시스템 전체가 한눈에 들어오실 겁니다! 😎
