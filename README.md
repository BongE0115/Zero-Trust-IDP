# 🛡️ Zero-Trust-IDP (Hybrid SRE Platform)

> **분산 하이브리드 워크로드(Active-Active)의 에러를 중앙으로 집결시키고, Zero-Trust 기반의 격리된 샌드박스에서 안전하게 복구하는 사내 개발자용 SRE 자동화 플랫폼**

## 💡 프로젝트 개요 (Overview)
클라우드 전역에 분산된 마이크로서비스 환경에서는 에러 추적과 디버깅이 매우 파편화되어 있습니다. 또한 장애 복구를 위해 운영망(AWS) DB에 개발자가 직접 접근하는 것은 심각한 보안 리스크를 초래합니다.

**Zero-Trust-IDP**는 이러한 문제를 해결하기 위해 고안된 하이브리드 클라우드 기반의 장애 대응 파이프라인입니다. 
퍼블릭 클라우드(AWS)와 사내망(On-Premises K8s) 어디서 에러가 발생하든 사내망의 **중앙 DLQ(Dead Letter Queue)**로 데이터를 모읍니다. 이후 AIOps 알람을 통해 원클릭으로 **망분리가 완벽히 적용된 일회용 포렌식 샌드박스**를 자동 배포하여, 운영망의 안전을 보장하면서도 빠르고 정확한 에러 재처리(Redrive)를 가능하게 합니다.

## ✨ 핵심 혁신 포인트 (Key Features)
* **Decentralized Services, Centralized Recovery:** Kafka의 디커플링을 활용하여, 인프라의 위치와 무관하게 발생하는 모든 치명적 에러를 사내 폐쇄망의 단일 샌드박스로 집중시킵니다.
* **Zero-Trust Network Isolation:** Istio의 `AuthorizationPolicy`를 통해 샌드박스 파드에서 외부 운영망(AWS RDS)으로 나가는 Egress 통신을 100% 원천 차단합니다.
* **GitOps & ChatOps Automation:** Slack 봇과 GitHub Actions, ArgoCD를 연동하여 에러 발생 시 즉각적으로 동일한 에러 환경을 재현하는 샌드박스를 On-Demand로 프로비저닝하고 회수(GC)합니다.
* **FinOps 기반 비용 최적화:** 전체 트래픽이 아닌 0.1% 미만의 에러 데이터만 사내망으로 전송하며, 페이로드 압축을 통해 퍼블릭 클라우드의 아웃바운드 비용을 최소화합니다.

## 🛠️ 기술 스택 (Tech Stack)
* **Infrastructure:** AWS (EC2, RDS), On-Premises (K3s), Terraform
* **Hybrid Network:** Tailscale (Mesh VPN)
* **Message Broker:** Apache Kafka (Main & DLQ Topic)
* **Security & Mesh:** Istio (Egress Gateway, mTLS)
* **CI/CD Automation:** GitHub Actions, ArgoCD
* **AIOps & Monitoring:** Salesforce Merlion, Prometheus, Grafana
* **Applications:** Python (FastAPI/Merlion), Slack Bolt API, MongoDB (Ephemeral DB)

## 📂 저장소 구조 (Monorepo Architecture)
```text
Zero-Trust-IDP/
├── .github/                      # 🤖 GitHub Actions (CI/CD 자동화)
│   └── workflows/
│       ├── ci-build.yml          # 코드 푸시 시 Docker 이미지 빌드 및 푸시
│       └── cd-sandbox.yml        # Slack 봇이 트리거하는 샌드박스 배포 파이프라인       
│       └── jit-debug.yml         # 🚨 Slack 버튼 클릭 시 트리거되어 파드에 netshoot 컨테이너를 붙이고 tcpdump를 실행하는 자동화 워크플로우
│
├── templates/
│   ├── setup_k3s.yml.tpl
│
├── terraform/                    # ☁️ 인프라 프로비저닝 (AWS)
│   ├── main.tf                   # EC2, RDS(MySQL), 보안 그룹(Security Group) 정의
│   ├── variables.tf              # DB 비밀번호, 리전 등 변수 관리
│   └── outputs.tf                # 생성된 EC2 IP, RDS 엔드포인트 출력
│
├── ansible/                      # 🌉 하이브리드 망 구성 (Tailscale + K3s)
│   ├── inventory.ini             # AWS EC2 및 로컬 PC의 IP/접속 정보
│   └── setup-hybrid.yml          # Tailscale VPN 연동 및 K3s 설치 자동화 스크립트         
│
├── k8s-manifests/                # ⛵ ArgoCD가 감시하는 K8s 선언문 (GitOps)
│   ├── core-infra/               # [공통 인프라] 항시 떠 있는 시스템
│   │   ├── kafka/                # Apache Kafka (Main/DLQ 토픽 설정)
│   │   ├── monitoring/           # Prometheus & Grafana (에러/트래픽 시각화)
│   │   └── merlion-ai/           # Salesforce Merlion (DLQ 이상 탐지 AI)
│   │       
│   ├── apps/                     # [메인 서비스] 비즈니스 로직
│   │   ├── consumer-aws/         # AWS에서 도는 메인 컨슈머 파드
│   │   ├── consumer-local/       # 로컬망에서 도는 메인 컨슈머 파드 (Active-Active)
│   │   └── redrive-api/          # 복구된 에러를 다시 메인 큐로 밀어넣는 API     
│   │
│   └── forensic-sandbox/         # 🛡️ [핵심] On-Demand 격리 샌드박스 구역
│       ├── sandbox-app.yaml      # [UPDATE] 앰비언트 메시 라벨 (istio.io/dataplane-mode: ambient) 적용
│       ├── mongodb-temp.yaml     # 샌드박스 전용 일회용 로컬 MongoDB    
│       ├── istio-rules.yaml      # L7 Egress 차단 룰 (AuthorizationPolicy)
│       ├── peer-auth.yaml        # 샌드박스 내 STRICT mTLS 강제 적용
│       ├── waypoint.yaml         # 앰비언트 메시의 L7 정책(차단 룰)을 실행할 Waypoint Proxy
│       └── network-policy.yaml   # K8s CNI 레벨의 물리적 심층 방어 (AWS RDS 등 외부 IP 원천 차단 화이트리스트)
│
├── src/                          # 💻 실제 애플리케이션 소스 코드
│   ├── consumer-app/             
│   ├── merlion-ai/               # (Python) 시계열 이상 탐지 앱
│   │   ├── model.py              # Merlion 시계열 모델 
│   │   └── slack_notifier.py     # 🚨 에러 포트 정보와 '디버깅 권한 부여(JIT)' 대화형 버튼을 Slack으로 쏘는 로직
│   └── redrive-api/              
│
├── .gitignore                    # 보안 키, tfstate, 로그 파일 등 업로드 방지
└── README.md                     # 프로젝트 개요, 아키텍처, 실행 가이드