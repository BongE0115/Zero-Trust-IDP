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


## 📂 저장소 구조 (Monorepo Architecture) - 축약 버전 
```text
04.06 slack 알람 추가 버전/
├─ terraform/                      # AWS 인프라 생성
│  ├─ main.tf                      # VPC/EC2/ALB/RDS 메인
│  └─ templates/                   # EC2 초기화 스크립트
│     ├─ k3s_server.sh.tpl         # master 부팅
│     ├─ k3s_agent.sh.tpl          # worker 부팅
│     └─ monitoring.sh.tpl         # monitoring 부팅
│
├─ .github/workflows/              # 자동화 파이프라인
│  ├─ activate-sandbox.yaml        # 샌드박스 생성
│  ├─ create-case-branch.yaml      # case 브랜치 생성
│  ├─ build-case-candidate.yaml    # 수정 이미지 빌드
│  ├─ revalidate-sandbox.yaml      # 수정 후 검증
│  ├─ promote-case-image.yaml      # 운영 승격
│  └─ redrive-dlq.yaml             # DLQ 재처리
│
├─ gitops/                         # ArgoCD가 보는 배포 원본
│  ├─ bootstrap/                   # root-app / child-app 정의
│  └─ apps/
│     ├─ kafka-poc/                # producer/consumer/dlq-handler
│     ├─ forensic-sandbox/         # 샌드박스 베이스 + case 파일
│     ├─ boutique-local/           # 로컬 앱
│     └─ boutique-production/      # 운영 앱
│
├─ forensic-launcher/              # 샌드박스 내부 launcher
│  └─ app/launcher.py              # 샌드박스 내부 컨슈머-app에 정상, 실패 메시지 주입 및 결과 정 
│
├─ ansible/                        # 하이브리드 설정 보조
├─ docs/case-lifecycle.md          # 메시지 처리 로직 설명 문서
├─ app.py                          # Slack 버튼 → GitHub Actions 호출
```text

## 📂 저장소 구조 (Monorepo Architecture) - 전체 버전
```text
04.06 slack 알람 추가 버전/
├─ terraform/                              # AWS 인프라를 만드는 Terraform 루트
│  ├─ main.tf                              # VPC, EC2, ALB, RDS 등 메인 인프라 정의
│  ├─ variables.tf                         # Terraform 입력 변수 정의
│  ├─ outputs.tf                           # 생성 후 출력값 정의
│  ├─ local_env.tf                         # 로컬/외부 연동용 설정
│  ├─ github_secrets.tf                    # GitHub Actions 시크릿/연동 관련 Terraform
│  ├─ scripts/                             # Terraform 보조 스크립트
│  │  └─ get_k3s_kubeconfig.py             # SSM으로 K3s kubeconfig 가져오는 스크립트
│  └─ templates/                           # EC2 user_data 템플릿
│     ├─ k3s_server.sh.tpl                 # K3s master 초기 설정 스크립트
│     ├─ k3s_agent.sh.tpl                  # K3s worker 초기 설정 스크립트
│     └─ monitoring.sh.tpl                 # monitoring 서버 초기 설정 스크립트
│
├─ .github/                                # GitHub Actions 워크플로우
│  └─ workflows/
│     ├─ activate-sandbox.yaml             # 샌드박스 생성 시작 워크플로우
│     ├─ build-and-push.yaml               # 기본 이미지 빌드/푸시
│     ├─ build-case-candidate.yaml         # case 전용 candidate 이미지 빌드
│     ├─ cleanup-case-sandbox.yaml         # case 샌드박스 정리
│     ├─ create-case-branch.yaml           # case 브랜치 생성
│     ├─ promote-case-image.yaml           # 검증 통과 이미지 운영 승격
│     ├─ redrive-dlq.yaml                  # DLQ 메시지 재처리
│     ├─ reproduce-sandbox.yaml            # 실패 재현용 샌드박스 실행
│     └─ revalidate-sandbox.yaml           # 수정 후 재검증 샌드박스 실행
│
├─ ansible/                                # Ansible 실행 파일
│  ├─ inventory.ini                        # 대상 서버 목록
│  └─ setup-hybrid.yml                     # 하이브리드 환경 설정 플레이북
│
├─ docs/                                   # 문서 폴더
│  └─ case-lifecycle.md                    # case 생성~승격 전체 흐름 문서
│
├─ forensic-launcher/                      # 샌드박스 내부 launcher 서비스
│  ├─ dockerfile                           # launcher 이미지 빌드 파일
│  ├─ requirements.txt                     # launcher 파이썬 패키지
│  └─ app/
│     └─ launcher.py                       # artifact 주입/판정/verdict 생성 로직
│
├─ gitops/                                 # ArgoCD가 바라보는 GitOps 루트
│  ├─ bootstrap/                           # ArgoCD 최초 부트스트랩 영역
│  │  ├─ root-app.yaml                     # 최상위 ArgoCD root app
│  │  ├─ argocd/
│  │  │  └─ values.yaml                    # ArgoCD 설치 values
│  │  └─ children/
│  │     ├─ argocd-app.yaml                # ArgoCD child app
│  │     ├─ boutique-local-app.yaml        # local 앱 child app
│  │     ├─ boutique-production-app.yaml   # production 앱 child app
│  │     ├─ forensic-sandbox-app.yaml      # sandbox base app
│  │     ├─ forensic-sandbox-cases-app.yaml# case sandbox app
│  │     ├─ forensic-sandbox-reproduce.yaml# reproduce app
│  │     ├─ forensic-sandbox-revalidation-app.yaml # revalidation app
│  │     ├─ istio-app.yaml                 # istio app
│  │     ├─ kafka-stack-app.yaml           # kafka stack app
│  │     └─ observability-app.yaml         # observability app
│  │
│  ├─ apps/                                # 실제 앱 매니페스트 모음
│  │  ├─ boutique-local/                   # 로컬 부티크 앱
│  │  │  ├─ cartservice.yaml               # cart 서비스 매니페스트
│  │  │  ├─ currencyservice.yaml           # currency 서비스 매니페스트
│  │  │  ├─ loadgenerator.yaml             # 테스트 트래픽 생성기
│  │  │  ├─ productcatalog.yaml            # 상품 카탈로그 서비스
│  │  │  └─ kustomization.yaml             # 묶음 배포 정의
│  │  │
│  │  ├─ boutique-production/              # 운영 부티크 앱
│  │  │  ├─ checkoutservice.yaml           # 결제/주문 흐름 서비스
│  │  │  ├─ frontend.yaml                  # 프론트엔드 서비스
│  │  │  ├─ hpa.yaml                       # 오토스케일 설정
│  │  │  ├─ paymentservice.yaml & shippingservice.yaml # 결제/배송 서비스
│  │  │  └─ kustomization.yaml             # 묶음 배포 정의
│  │  │
│  │  ├─ kafka-poc/                        # 장애 처리 실험용 Kafka 앱
│  │  │  └─ manifests/
│  │  │     ├─ 00-namespace.yaml           # POC 네임스페이스
│  │  │     ├─ 01-kafka.yaml               # Kafka 관련 배포
│  │  │     ├─ 02-topics-job.yaml          # 토픽 생성 Job
│  │  │     ├─ 11-producer.yaml            # producer 파드
│  │  │     ├─ 21-consumer.yaml            # consumer 파드
│  │  │     ├─ 30-dlq-handler-rbac.yaml    # DLQ handler 권한
│  │  │     ├─ 32-dlq-handler.yaml         # DLQ handler 파드/서비스
│  │  │     └─ kustomization.yaml          # 묶음 배포 정의
│  │  │
│  │  └─ forensic-sandbox/                 # 샌드박스 GitOps 영역
│  │     ├─ templates/
│  │     │  └─ sandbox-app.yaml            # 샌드박스 앱 템플릿
│  │     ├─ base/
│  │     │  ├─ current-case.yaml           # 현재 case 참조 정보
│  │     │  ├─ istio-rules.yaml            # sandbox 네트워크 규칙
│  │     │  ├─ kustomization.yaml          # sandbox base 묶음 정의
│  │     │  ├─ network-policy.yaml         # 접근 제한 정책
│  │     │  ├─ peer-auth.yaml              # 보안 통신 정책
│  │     │  ├─ sandbox-app-sa.yaml         # 서비스어카운트
│  │     │  ├─ sandbox-developer-rbac.yaml # 개발자 접근 권한
│  │     │  └─ waypoint.yaml               # 네트워크/트래픽 관련 설정
│  │     │
│  │     └─ cases/                         # case별 동적 생성 파일
│  │        ├─ .gitkeep                    # 빈 폴더 유지용
│  │        ├─ sandbox-case-*.yaml         # case별 샌드박스 배포 파일
│  │        ├─ artifacts/                  # case 입력/재처리 artifact
│  │        │  └─ <case-id>/
│  │        │     ├─ failure.json          # 실패 재현 입력
│  │        │     ├─ normal.json           # 정상 검증 입력
│  │        │     └─ redrive.json          # 운영 재처리 입력
│  │        ├─ records/                    # case 상태 기록 파일
│  │        │  ├─ .gitkeep                 # 빈 폴더 유지용
│  │        │  └─ <case-id>.json           # branch/candidate/verdict 상태 기록
│  │        ├─ reproduce/                  # 실패 재현용 job 파일
│  │        │  ├─ .gitkeep                 # 빈 폴더 유지용
│  │        │  └─ reproduce-case-*.yaml    # 재현 job
│  │        ├─ revalidation/               # 수정 후 검증용 job 파일
│  │        │  ├─ .gitkeep                 # 빈 폴더 유지용
│  │        │  └─ revalidate-case-*.yaml   # 재검증 job
│  │        ├─ templates/
│  │        │  └─ revalidation-job.yaml    # 재검증 job 템플릿
│  │        └─ verdicts/                   # 검증 결과 스냅샷
│  │           ├─ .gitkeep                 # 빈 폴더 유지용
│  │           └─ *.json                   # verdict 결과 파일
│  │
│  └─ platform/
│     └─ istio/                            # istio 플랫폼 설정 폴더
│     └─ observability                     # Prometheus, Grapana 설정 폴더 
│ 
├─ scripts/                                    # GitHub Actions/운영 자동화 보조 스크립트
│  ├─ apply_sandbox_spec.py                    # spec json을 case용 sandbox yaml로 변환
│  ├─ collect_revalidation_result.py           # verdict 읽어 case record 갱신
│  ├─ export_verdict_snapshot.py               # pod 안 verdict를 repo 파일로 저장
│  ├─ patch_case_candidate.py                  # case sandbox yaml의 이미지 태그 교체
│  ├─ promote_verified_image.py                # 검증 통과 이미지를 운영 manifest에 반영
│  ├─ redrive_case_messages.py                 # DLQ 메시지를 운영 토픽으로 재전송
│  ├─ render_revalidation_job.py               # 재검증 job yaml 생성
│  └─ update_case_record.py                    # case 상태 json 생성/업데이트
│ 
│ 
├─ services/                                   # 실제 실행되는 애플리케이션 코드
│  ├─ dlq-handler/                             # 장애 이벤트 수집/샌드박스 생성 트리거 서비스
│  │  ├─ dockerfile                            # dlq-handler 이미지 빌드
│  │  ├─ requirements.txt                      # dlq-handler 패키지
│  │  └─ app/
│  │     ├─ handler.py                         # DLQ 감시, 3개 json 생성, 후속 트리거 핵심 로직
│  │     └─ slack_notifier.py                  # Slack 알림/버튼 메시지 전송 로직
│  │
│  ├─ producer-api/                            # 테스트용 주문/메시지 발행 API
│  │  ├─ dockerfile                            # producer-api 이미지 빌드
│  │  ├─ requirements.txt                      # producer-api 패키지
│  │  └─ app/
│  │     └─ app.py                             # 요청 받아 Kafka로 메시지 발행
│  │
│  └─ worker-consumer/                         # 운영 consumer + 샌드박스 재현 대상 서비스
│     ├─ dockerfile                            # worker-consumer 이미지 빌드
│     ├─ requirements.txt                      # worker-consumer 패키지
│     └─ app/
│        ├─ business_logic.py                  # 실제 주문 처리/실패 조건 로직
│        ├─ consumer.py                        # Kafka 메시지 소비 진입점
│        ├─ failure_event.py                   # 운영 실패 시 DLQ 이벤트 생성
│        ├─ runtime_context.py                 # 운영/샌드박스 모드 환경값 읽기
│        └─ sandbox_result.py                  # 샌드박스 결과 이벤트 생성

│  └─ slack-receiver/
│        ├─ app.py                              # Slack 버튼 수신 → GitHub Actions dispatch 호출
│        ├─ dockerfile                          # Slack receiver 이미지 빌드
│        └─ requirements.txt                    # Slack receiver 패키지
