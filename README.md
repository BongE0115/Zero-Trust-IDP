# 🛡️ Zero-Trust-IDP (Hybrid SRE Platform)

> **분산 하이브리드 워크로드(Active-Active)의 에러를 중앙으로 집결시키고, Zero-Trust 기반의 격리된 샌드박스에서 안전하게 복구하는 사내 개발자용 SRE 자동화 플랫폼**

# 📌 Overview

현대의 마이크로서비스 환경은 AWS, 온프레미스, 쿠버네티스 등 여러 인프라에 분산되어 운영됩니다.
이 구조는 확장성과 유연성을 제공하지만, 장애가 발생했을 때 다음과 같은 문제를 만들기도 합니다.

1. 장애 로그와 실패 이벤트가 여러 위치에 흩어져 있어 추적이 어렵다.
2. 운영 DB나 운영 클러스터에 직접 접근해야만 원인 분석이 가능한 경우가 많다.
3. 개발자가 복구를 위해 운영망에 직접 접근하면 보안과 안정성 측면에서 큰 리스크가 발생한다.
4. 수정된 코드가 실제로 문제를 해결했는지, 또 정상 동작까지 보장하는지 검증하기 어렵다.

Zero-Trust-IDP는 이러한 문제를 해결하기 위해 설계된 Hybrid SRE Incident Response Platform입니다.
AWS와 On-Premises 환경 어디서 발생한 장애든 Kafka 기반 DLQ로 중앙 수집하고, GitOps + ChatOps 파이프라인을 통해 격리된 포렌식 샌드박스를 자동 생성합니다.
개발자는 이 샌드박스 안에서 동일한 실패를 안전하게 재현하고, 수정한 코드를 검증한 뒤, 검증이 완료된 이미지에 대해서만 운영 반영을 수행할 수 있습니다.

 즉, 이 프로젝트의 핵심은 단순한 “에러 알림 시스템”이 아니라 

**장애 수집 → 샌드박스 재현 → 수정 검증 → 운영 반영 → 실패 메시지 재처리**

까지 이어지는 폐쇄형 자동 복구 파이프라인을 구현하는 것입니다.

## 🎯 목표 (Goal) 

이 프로젝트의 목표는 다음과 같습니다.

분산된 하이브리드 워크로드에서 발생하는 장애를 중앙 집중형 흐름으로 수렴
운영망과 개발/분석 환경을 완전히 분리한 Zero-Trust 복구 체계 구축
동일한 실패를 재현할 수 있는 일회용 샌드박스 자동 생성
수정 코드가 실제 문제를 해결했는지 검증하는 재현 + 재검증 자동화
검증된 이미지만 운영에 반영하는 안전한 GitOps 기반 승격(promote)
장애로 인해 적재된 실패 메시지를 다시 처리하는 Redrive 자동화

## ✨ 핵심 혁신 포인트 (Key Features)
**1. 분산된 장애를 중앙 DLQ로 수렴하여**, 인프라 위치와 무관한 통합 복구 체계를 제공합니다.

**2. Istio 기반 Zero-Trust 샌드박스 격리를 적용해**, 샌드박스를 별도 네임스페이스와 사이드카가 포함된 서비스 메시 내부에 배치하고, AuthorizationPolicy 기반 기본 차단(Default Deny) 정책 아래에서 **사건별 replay/result topic만 허용**하도록 구성했습니다.
이를 통해 **운영 서비스·운영 DB로의 직접 접근을 차단하고, 분석 과정에서 운영망 오염이 확산되는 것을 막습니다.**

**3. 사건별 일회용 포렌식 샌드박스를 자동 생성**해, 공용 테스트 환경의 한계를 극복합니다. 각 샌드박스는 해당 사건의 payload, consumer image, validation mode를 반영해 독립적으로 구성되며, 검증 종료 후 자동 정리됩니다.

**4. 실패/정상 케이스를 모두 통과한 수정만 운영 반영**하여, 단순한 패치 배포가 아니라 검증된 수정만 승격되는 복구 체계를 제공합니다.

**5. 수집–재현–검증–반영–재처리**까지 연결된 폐쇄형 자동 복구 파이프라인을 통해, 알림 중심의 기존 장애 대응을 실제 복구 중심 구조로 전환합니다.

**6. GitOps + ChatOps 기반 운영 표준화**를 통해, 장애 대응을 담당자 경험과 수동 명령에 의존하는 방식에서 실행 가능하고 추적 가능한 플랫폼형 프로세스로 전환합니다.

## 🛠️ 기술 스택 (Tech Stack)
* **Infrastructure:** AWS (EC2, RDS), On-Premises (K3s), Terraform
* **Hybrid Network:** Tailscale (Mesh VPN)
* **Message Broker:** Kafka(main, DLQ, Replay, Result Topic)
* **Security & Mesh:** Istio (Egress Gateway, mTLS), AutorizationPolicy, NetworkPolicy
* **CI/CD Automation:** GitHub Actions, ArgoCD
* **Monitoring:** Prometheus, Grafana, Slack Bot, Slack Webhook


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
