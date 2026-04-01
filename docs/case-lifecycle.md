# Case Lifecycle

이 문서는 forensic sandbox 기반 장애 재현, 개발자 수정, 재검증, 운영 승격 과정에서
case 상태 파일이 어떤 의미를 가지는지 설명한다.

## 목적

case 상태는 아래 문제를 막기 위해 Git에 기록된다.

- 여러 case가 동시에 열릴 때 상태가 섞이는 문제
- sandbox는 떴는데 기록이 없는 문제
- candidate 이미지는 빌드됐는데 어떤 case 것인지 모르는 문제
- 재검증 통과 이미지와 운영 승격 이미지가 달라지는 문제
- redrive, cleanup, rollback 기준이 모호한 문제

즉, `gitops/apps/forensic-sandbox/cases/records/` 아래의 JSON 파일은
case lifecycle의 단일 상태 기록(source of truth)이다.

---

## 경로 규칙

- case record directory:
  - `gitops/apps/forensic-sandbox/cases/records/`
- case record file:
  - `gitops/apps/forensic-sandbox/cases/records/<case-id>.json`

예:
- `gitops/apps/forensic-sandbox/cases/records/worker-consumer-123-20260331T010203Z-abcd1234.json`

---

## 브랜치 규칙

개발자 작업 브랜치는 아래 형식을 따른다.

- `case/<case-id>`

예:
- `case/worker-consumer-123-20260331T010203Z-abcd1234`

중요:
- `case/<case-id>` 는 운영 배포 브랜치가 아니다.
- 이 브랜치는 수정/검증용 격리 브랜치다.
- merge와 promote는 같은 의미가 아니다.

---

## merge 와 promote 의 차이

### merge
- 개발자가 수정한 코드를 코드 이력 측면에서 통합하는 행위
- 코드 변경 내역을 브랜치에 반영하는 것

### promote
- sandbox에서 검증을 통과한 **바로 그 이미지 digest**를 운영 manifest에 반영하는 행위
- 운영 배포 행위

즉:

- merge != promote
- promote는 반드시 revalidation을 통과한 verified image digest 기준으로 수행한다.
- promote 시점에 새 이미지를 다시 빌드해서 운영에 반영하면 안 된다.

---

## case 상태 파일 형식

각 case 상태 파일은 JSON 형식을 사용한다.

기본 예시는 아래와 같다.

```json
{
  "case_id": "worker-consumer-123-20260331T010203Z-abcd1234",
  "service": "worker-consumer",
  "branch_name": "case/worker-consumer-123-20260331T010203Z-abcd1234",
  "status": "sandbox_created",
  "created_at": "2026-03-31T01:02:03Z",
  "updated_at": "2026-03-31T01:02:03Z",
  "source_image_ref": "ghcr.io/example/worker-consumer@sha256:old",
  "candidate_image_ref": null,
  "verified_image_ref": null,
  "promoted_image_ref": null,
  "previous_production_image_ref": null,
  "sandbox_manifest_path": "gitops/apps/forensic-sandbox/cases/sandbox-case-worker-consumer-123-20260331T010203Z-abcd1234.yaml",
  "revalidation_generation": 0,
  "validation_run_id": null,
  "redrive_count": 0,
  "flags": {
    "revalidation_passed": false,
    "promoted": false,
    "redriven": false,
    "resolved": false,
    "cleanup_completed": false
  },
  "metadata": {},
  "history": [
    {
      "at": "2026-03-31T01:02:03Z",
      "action": "create",
      "status": "sandbox_created"
    }
  ]
}