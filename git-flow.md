# Git Flow (UpdateBoard)

이 문서는 UpdateBoard 프로젝트의 **브랜치 / 커밋 / PR / 태그 / 이슈 / 마일스톤 / 레이블** 의 모든 규칙을 정의한다. 모든 코드 작업은 이 규칙을 따른다.

---

## 0. 핵심 원칙

### 0.1. 언어 규칙

| 대상 | 언어 |
|---|---|
| 저장소 내 문서 (`README.md`, `docs/*.md`) | **한글** |
| 코드 주석 | **한글** |
| 브랜치명 | **영어 소문자 + 하이픈** |
| 커밋 메시지 | **영어** (Conventional Commits) |
| GitHub Milestone / Issue / PR | **영어** |

### 0.2. Milestone & Issue 의무

모든 작업은 **Milestone → Issue → Branch → PR** 의 위계를 가진다. 고아 작업은 허용하지 않는다.

| 항목 | 일반 작업 | hotfix 예외 |
|---|---|---|
| Milestone | ✅ 필수 | ❌ 없어도 됨 (긴급 사고는 미리 계획되지 않음) |
| Issue | ✅ 필수 | ✅ 필수 |

마일스톤과 이슈는 **개발 시작 전 계획 단계에서 일괄 정의** 한다. 계획 이후에 마일스톤이나 이슈를 추가해야 한다면 **반드시 논의 후 추가** 한다.

### 0.3. 책임 분리

| 작업 | 담당 |
|---|---|
| Milestone / Issue / Branch / commit / push / PR 생성 | 누구나 (자동화 가능) |
| PR assignee 등록 | 작성자 본인 |
| PR 코드 리뷰 | 저장소 관리자 |
| PR Approve 및 **Merge** | **저장소 관리자만** |
| Merge 후 후처리 (label/milestone/branch 정리) | 누구나 |

> 자동화 도구가 PR 까지 만들 수 있어도, **최종 merge 권한은 사람만** 가진다.

---

## 1. 브랜치 모델

### 1.1. 명명 규칙

```
<type>/#<issueNumber>-<summary>
```

- `<type>` — 브랜치 종류 (아래 표 참고)
- `#<issueNumber>` — GitHub Issue 번호 (필수)
- `<summary>` — 짧은 작업 요약, 영문 소문자 + 하이픈 연결, 띄어쓰기 금지

**예시**

```
feature/#1-admin-login
fix/#20-jwt-expiry
refactor/#13-folder-structure
hotfix/#99-prd-db-error
```

**예외**: `main`, `develop` 은 명칭이 변하지 않으며 절대 삭제하지 않는다.

### 1.2. 브랜치 전략표

브랜치 타입은 commit type 과 1:1 매칭된다.

| 타입 | 의미 | 예시 | 분기 출처 | Jenkins 자동 빌드 | 대응 commit type |
|---|---|---|---|---|---|
| `main` | 운영 배포 상태 | `main` | — | ✅ 운영 컨테이너 (`updateboard-run-release`) | (직접 커밋 금지) |
| `develop` | 다음 배포 통합 | `develop` | — | ✅ 개발 컨테이너 (`updateboard-run-debug`) | (직접 커밋 금지) |
| `feature/*` | 새 기능 개발 | `feature/#1-admin-login` | `develop` | ❌ | `feat` |
| `fix/*` | 개발 중 버그 수정 | `fix/#20-jwt-error` | `develop` | ❌ | `fix` |
| `refactor/*` | 기능 변경 없는 코드 개선 | `refactor/#13-folder-structure` | `develop` | ❌ | `refactor` |
| `docs/*` | 문서 작업 | `docs/#1-establish-git-flow` | `develop` | ❌ | `docs` |
| `chore/*` | 설정/패키지/CI 등 | `chore/#7-prisma-setup` | `develop` | ❌ | `chore`, `ci` |
| `hotfix/*` | 운영 긴급 수정 | `hotfix/#99-prd-db-error` | `main` | ✅ 개발 컨테이너 (검증용) | `fix` |

> **참고** — 본 프로젝트는 `release/*` 브랜치를 사용하지 않는다. 정기 배포는 `develop → main` 직접 merge 로 진행한다.

> **주의** — Jenkins 가 자동 빌드하지 않는 브랜치 (`feature/*`, `fix/*`, `refactor/*`) 도 push 자체는 가능하다. 단지 자동 빌드/배포가 트리거되지 않을 뿐이다. 검증은 PR merge 후 develop/main 에서 자동으로 일어난다.

---

## 2. 브랜치 생명주기

### 2.1. 준비

- `main` 브랜치 — 항상 운영 배포 가능 상태 유지
- `develop` 브랜치 — `main` 에서 분기, 다음 정기 배포까지 통합
- 두 브랜치는 **절대 삭제하지 않는다**

### 2.2. 일반 개발 사이클

```
0. (계획 단계) 마일스톤과 이슈가 이미 생성되어 있어야 함
1. develop 에서 feature/#N-summary 분기
2. 로컬에서 개발 + 커밋
3. push origin feature/#N-summary
4. GitHub 에서 PR 생성 (feature → develop)
   - assignee 등록
   - 이슈에 부착된 label 그대로 PR 에도 적용
   - milestone 연결
   - PR 본문에 "Closes #N" 명시
5. 코드 리뷰 → Approve → merge (관리자만)
6. Jenkins 가 develop 자동 빌드 → 개발 컨테이너 갱신
7. 후처리:
   - 이슈가 자동 닫혔는지 확인
   - 이슈/PR 의 status label: in-progress → done
   - 마일스톤의 모든 이슈가 닫혔다면 마일스톤도 닫기
   - feature 브랜치 삭제 (origin + local)
```

### 2.3. 정기 배포 (develop → main)

```
1. develop 에서 충분한 검증 완료
2. GitHub 에서 PR 생성 (develop → main)
3. PR 본문에 변경 요약 작성
4. 코드 리뷰 → Approve → merge (관리자만)
5. Jenkins 가 main 자동 빌드 → 운영 컨테이너 갱신
6. main 브랜치에 새 버전 태그 (`vX.Y.0`) 생성
```

### 2.4. 긴급 배포 (hotfix)

운영(`main`) 에서 긴급한 버그가 발견되었을 때 사용한다.

```
0. 이슈 생성 (마일스톤은 생략 가능 — 사고는 계획 불가)
1. main 에서 hotfix/#N-summary 분기
2. 로컬에서 수정 + 커밋
3. push origin hotfix/#N-summary
4. Jenkins 가 자동으로 개발 컨테이너에 배포 (스테이징 검증)
5. 개발 환경에서 수정 효과 검증
   ⚠ 이 단계가 통과되기 전에는 절대 main 으로 PR merge 하지 않는다
6. 검증 통과 후 GitHub 에서 PR 생성 (hotfix → main)
7. 코드 리뷰 → Approve → merge (관리자만)
8. Jenkins 가 main 자동 빌드 → 운영 컨테이너 갱신
9. main 브랜치에 패치 버전 태그 (`vX.Y.Z`) 생성
10. develop 으로 백머지 (변경사항 동기화)
11. hotfix 브랜치 삭제
```

**왜 develop 으로 백머지가 필요한가?** hotfix 의 수정사항이 develop 에도 들어가지 않으면, 다음 정기 배포 때 같은 버그가 다시 운영에 나타날 수 있다.

---

## 3. Milestone

### 3.1. 명명 규칙

```
Phase <N>: <Title>
```

- `<N>` — 단계 번호 (Phase 1, 2, 3, ...)
- `<Title>` — 영어 제목 (Title Case)

**예시**

```
Phase 1: Initial Setup
Phase 2: Core API
Phase 3: Admin UI
Phase 4: Authentication
```

### 3.2. 운영 원칙

- **계획 단계에서 일괄 정의** — 본격 개발 시작 전에 전체 Phase 구조를 잡는다
- **추가는 논의 후** — 계획 이후에 새 마일스톤 추가가 필요하면 반드시 논의를 거친다
- **마일스톤 닫기** — 해당 마일스톤의 모든 이슈가 닫히면 마일스톤도 닫는다

---

## 4. Issue

### 4.1. 타이틀 명명법

커밋/PR 과 동일한 Conventional Commits 형식을 사용한다.

```
<type>: <Imperative sentence>
```

| 규칙 | 내용 |
|---|---|
| 타입 | `feat`, `fix`, `refactor`, `chore`, `docs`, `test`, `style`, `ci` |
| 동사 시제 | **명령형 (Imperative)** — "Implement", "Add", "Fix", "Refactor" |
| 첫 글자 | 대문자 시작 (Sentence case) |
| 길이 | 72자 이내 |
| 마침표 | 끝에 마침표 없음 |
| 이슈 번호 | 타이틀에 포함하지 않음 (GitHub 가 자동 부여) |

**예시**

```
feat: Implement admin login page
feat: Add version lookup API endpoint
fix: Resolve JWT token expiry calculation
refactor: Reorganize app folder structure
docs: Establish git-flow guidelines and PR template
chore: Configure Prisma with MariaDB
test: Add unit tests for version comparison
ci: Update Jenkinsfile branch matrix
```

### 4.2. 이슈 본문

영어로 작성. 다음 정보 포함

- **Summary** — 무엇을 왜 하는지 한 문단
- **Goals** — 달성 목표 목록
- **Tasks** — 체크박스 형태 작업 단위
- (선택) **References** — 관련 이슈/문서 링크

### 4.3. 이슈에 부착할 레이블

모든 이슈에는 **type / priority / status 각 1개씩** 부착 (총 3개).

---

## 5. Commit Message

### 5.1. 형식

```
<type>: <설명> (#<issueNumber>)
```

또는 이슈를 닫고 싶을 때

```
<type>: <설명> (Closes #<issueNumber>)
```

### 5.2. 타입 (Conventional Commits)

| 타입 | 의미 | 버전 영향 |
|---|---|---|
| `feat` | 새로운 기능 추가 | MINOR 상승 근거 |
| `fix` | 버그 수정 | hotfix 인 경우 PATCH 상승 |
| `feat!` | BREAKING CHANGE — 이전 버전과 호환 불가 | MAJOR 상승 근거 |
| `refactor` | 기능 변경 없는 코드 구조/성능 개선 | 영향 없음 |
| `test` | 테스트 코드 작성/수정 | 영향 없음 |
| `chore` | 빌드 설정, 패키지 업데이트 등 | 영향 없음 |
| `docs` | 문서 변경만 | 영향 없음 |
| `style` | 코드 동작과 무관한 포맷/공백 변경 | 영향 없음 |
| `ci` | CI/CD 설정 변경 (Jenkinsfile 등) | 영향 없음 |

### 5.3. 이슈 키워드

PR 본문 또는 커밋 메시지에 다음 키워드를 사용하면 PR merge 시 자동으로 이슈가 닫힌다.

| 키워드 | 의미 |
|---|---|
| `Closes #N` | 일반적인 작업 완료 (feat 등) |
| `Fixes #N` | 버그 수정 완료 |
| `Resolves #N` | 무언가 해결 완료 |

**예시**

```
feat: Implement admin login page (Closes #1)
fix: Resolve JWT expiry calculation (Fixes #20)
refactor: Reorganize folder structure (Resolves #13)
```

### 5.4. 브랜치 × 타입 매트릭스

| 브랜치 | feat | fix | feat! | refactor | test/chore/style/docs/ci |
|---|---|---|---|---|---|
| `main` | ❌ | ❌ | ❌ | ❌ | ❌ |
| `develop` | ❌ | ❌ | ❌ | ❌ | ❌ |
| `feature/*` | ⭕ (주력) | ⭕ | ⭕ | ⭕ | ⭕ |
| `fix/*` | ❌ | ⭕ (주력) | ❌ | 🔺 (최소한) | ⭕ |
| `refactor/*` | ❌ | ❌ | ❌ | ⭕ (주력) | ⭕ |
| `hotfix/*` | ❌ | ⭕ (주력) | ❌ | ❌ | ⭕ |

> **`main` 과 `develop` 은 직접 커밋 금지** — 오직 PR merge 만 허용한다.

---

## 6. Pull Request

### 6.1. 타이틀

PR 은 결국 `main` 또는 `develop` 의 커밋이 되므로 **커밋 메시지 규칙과 동일** 하게 작성한다.

```
<type>: <요약> (#<issueNumber>)
```

### 6.2. 본문

`.github/pull_request_template.md` 가 PR 생성 시 자동으로 본문을 채워준다. 빈 곳은 모두 채우거나 "없을시 비워둠" 안내에 맞춰 처리한다.

본문에는 반드시 **`Closes #<issueNumber>`** (또는 `Fixes`, `Resolves`) 키워드를 포함하여 merge 시 이슈가 자동으로 닫히게 한다.

### 6.3. PR 메타데이터 (생성 시 등록)

| 항목 | 내용 |
|---|---|
| **Assignee** | 작업 담당자 본인 |
| **Reviewer** | 저장소 관리자 (GitHub 제약상 자동 등록 불가 시 수동 등록) |
| **Labels** | 이슈에 부착된 type / priority / status 그대로 복사 |
| **Milestone** | 이슈와 동일한 마일스톤 |
| **Linked Issue** | 본문에 `Closes #N` 으로 연결 |

### 6.4. 머지 규칙

| 출처 | 대상 | 비고 |
|---|---|---|
| `feature/*` / `fix/*` / `refactor/*` / `docs/*` / `chore/*` | `develop` | 일반 개발 |
| `develop` | `main` | 정기 배포 |
| `hotfix/*` | `main` | 긴급 배포 (debug 검증 통과 후) |
| `main` | `develop` | hotfix 백머지 (수동) |

### 6.5. 머지 전략

본 프로젝트는 **Create a merge commit** 전략만 사용한다. Squash merge 와 Rebase merge 는 GitHub 저장소 설정에서 비활성화되어 있다.

| 항목 | 값 |
|---|---|
| 전략 | Create a merge commit (개별 커밋 보존) |
| 머지 커밋 title | `PR_TITLE` (PR 타이틀을 자동 사용) |
| 머지 커밋 body | `PR_BODY` (PR 본문을 자동 사용) |
| 머지 후 브랜치 | 자동 삭제 (`delete_branch_on_merge: true`) |

#### 왜 이 전략인가

- **개별 커밋 히스토리 보존** — `git blame`, `git log`, `git bisect` 의 정확도 유지. 작업 진행 과정 추적 가능
- **시각적 PR 경계** — `git log --graph` 에서 머지 커밋을 통해 PR 단위가 명확히 구분됨
- **깔끔한 머지 메시지** — GitHub 의 기본 `Merge pull request #N from ...` 대신 PR 타이틀이 그대로 머지 커밋 메시지가 되므로, develop/main 의 history 가 Conventional Commits 를 따르는 깔끔한 형태가 됨
- **revert 단위 유연성** — PR 전체 revert (머지 커밋 revert) 또는 개별 커밋 revert 모두 가능

#### `git log --graph` 결과 예시

```
*   docs: Establish git-flow guidelines and PR template (#1)
|\
| * docs: Add PR template
| * docs: Write git-flow.md
|/
*   feat: Implement admin login page (#5)
|\
| * feat: Add login form component
| * feat: Add login validation
|/
*   ...
```

머지 커밋 자체가 PR 타이틀이고, 그 안에 개별 커밋들이 전부 보존된다.

#### Squash / Rebase 를 쓰지 않는 이유

- **Squash** — 개별 커밋이 사라져서 작업 과정과 `git blame` 정밀도를 잃는다
- **Rebase** — PR 단위 시각적 경계가 사라지고 revert 단위가 모호해진다

### 6.5. Merge 후 후처리

PR 이 merge 된 후 다음 단계를 수행한다.

- [ ] 이슈가 자동 닫혔는지 확인 (`Closes #N` 키워드가 있었으면 자동)
- [ ] 이슈의 status label: `in-progress` 제거 → `done` 부착
- [ ] PR 의 status label: 동일하게 `done` 으로 변경
- [ ] 마일스톤 확인: 해당 마일스톤의 모든 이슈가 닫혔다면 마일스톤도 닫기
- [ ] 머지된 브랜치 삭제 (origin + local)

---

## 7. Tag and Versioning (SemVer)

### 7.1. 형식

```
v<MAJOR>.<MINOR>.<PATCH>
```

예: `v1.0.0`, `v1.2.3`

### 7.2. 태그 생성 시점

태그는 **오직 `main` 브랜치에 코드가 머지된 직후에만** 생성한다.

| 시나리오 | 버전 변화 | 예 |
|---|---|---|
| 정기 배포 (develop → main, BREAKING CHANGE 포함) | MAJOR 상승 | `v1.2.3` → `v2.0.0` |
| 정기 배포 (develop → main, 신기능 포함) | MINOR 상승 | `v1.2.3` → `v1.3.0` |
| 긴급 배포 (hotfix → main) | PATCH 상승 | `v1.2.3` → `v1.2.4` |

### 7.3. 버전 결정 기준 (Conventional Commits)

대상 머지에 포함된 커밋의 가장 큰 변화에 맞춰 결정한다.

- 하나라도 `feat!` (BREAKING CHANGE) 포함 → MAJOR 상승
- 하나라도 `feat` 포함 (BREAKING 없음) → MINOR 상승
- `fix` 만 포함 → PATCH 상승

---

## 8. GitHub Labels

이슈와 PR 에는 다음 레이블 체계를 적용한다. 모든 이슈는 **타입 1개 + 우선순위 1개 + 상태 1개** 를 부착한다.

### 8.1. 타입 (Type)

| 레이블 | 의미 | 대응 commit type |
|---|---|---|
| `type: feature` | 새로운 기능 개발 | `feat` |
| `type: bug` | 버그 | `fix` |
| `type: design` | 디자인 작업 | (별도) |
| `type: refactor` | 리팩토링 | `refactor` |
| `type: improvement` | 기존 기능 개선 | `feat` 또는 `refactor` |
| `type: chore` | 설정 / 잡일 | `chore`, `ci` |
| `type: documentation` | 문서 작업 | `docs` |

> `test`, `style` 은 별도 type label 없이 type 은 작업 맥락에 가장 가까운 것으로 부착한다.

### 8.2. 우선순위 (Priority)

| 레이블 | 의미 |
|---|---|
| `priority: urgent` | 즉시 처리 (보통 hotfix) |
| `priority: high` | 빠른 처리 필요 |
| `priority: medium` | 보통 |
| `priority: low` | 여유 있을 때 |

### 8.3. 상태 (Status)

| 레이블 | 의미 | 변경 시점 |
|---|---|---|
| `status: ready` | 작업 시작 가능 | 이슈 생성 직후 (작업 미착수) |
| `status: in-progress` | 작업 진행 중 | 브랜치 생성 또는 작업 시작 시 |
| `status: done` | 작업 완료 | PR merge 후 |

---

## 9. 작업 시작 체크리스트

새 작업을 시작할 때

- [ ] 마일스톤이 이미 정의되어 있는가? (없으면 먼저 정의/논의)
- [ ] 영어로 GitHub Issue 생성 (`<type>: <Imperative>`, 본문 영어)
- [ ] 이슈에 type / priority / status 레이블 3개 부착
- [ ] 이슈를 마일스톤에 연결 (hotfix 제외)
- [ ] 적절한 브랜치 분기 출처 확인 (feature/refactor → develop, hotfix → main)
- [ ] 명명 규칙대로 브랜치 생성 (`<type>/#<issue>-<summary>`)
- [ ] 작업 + Conventional Commits 형식으로 커밋 (영어)
- [ ] push 후 PR 생성 (영어, 타이틀과 본문 규칙 준수)
- [ ] PR 에 assignee, label, milestone 부착, 본문에 `Closes #N`
- [ ] 코드 리뷰 → 관리자가 Merge
- [ ] Merge 후 후처리 (label 변경, 마일스톤 정리, 브랜치 삭제)
