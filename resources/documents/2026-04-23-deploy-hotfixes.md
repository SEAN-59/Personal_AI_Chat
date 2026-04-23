# 2026-04-22 ~ 04-23 개발 로그 — 프로덕션 배포 핫픽스 시리즈

## 배경
`v0.3.0`으로 프로덕션 배포 파이프라인(GitHub Actions → GHCR → 운영 호스트)을 첫 가동했으나, 로컬에서는 재현되지 않던 3가지 이슈가 실제 운영 호스트에서 순차적으로 드러남. 각각을 **독립된 hotfix 브랜치 + PR + 태그**로 관리해 역추적과 롤백 가능성을 유지.

릴리즈 흐름:
```
v0.3.0 (release)    ← 파이프라인 완성, 배포 시도 시 deploy 잡 실패
  ↓
v0.3.1 (hotfix)     ← SSH 배포의 PATH 문제
  ↓
v0.3.2 (hotfix)     ← 컨테이너-호스트 간 권한 불일치
  ↓
v0.3.3 (hotfix)     ← /media/ 서빙 누락
  ↓
main → develop back-merge (PR #14)
```

---

## 1. v0.3.1 — SSH 배포의 PATH 문제

**증상**
`v0.3.0` 태그 푸시 후 Actions `deploy` 잡이 `sh: docker: command not found` 로 즉시 실패.

**원인**
운영 호스트의 `docker` 바이너리는 `/usr/local/bin/docker` (실제 위치는 컨테이너 매니저 패키지 경로의 심볼릭 링크). 대화식 로그인에서는 `/etc/profile`이 이 경로를 PATH에 넣어주지만, **Actions가 열어 실행하는 비대화식 SSH 세션은 `/etc/profile`을 소싱하지 않음** → `/usr/local/bin`이 PATH에 없어 `docker` 해석 실패.

**해결 (`.github/workflows/deploy.yml`)**
원격 명령 맨 앞에 PATH 보강:
```
export PATH=/usr/local/bin:/usr/local/sbin:$PATH && \
cd <DEPLOY_PATH> && ...
```

**연결**
- Issue #8 / PR #9 / Tag `v0.3.1`
- 변경: `.github/workflows/deploy.yml` 1파일, 1줄 추가

**배운 점**
대화식/비대화식 쉘의 환경 차이는 CI 도구가 원격 호스트를 조작할 때 가장 흔하게 밟는 지뢰. "로컬 SSH는 되는데 Actions만 실패"면 이 카테고리가 1순위 의심 대상.

---

## 2. v0.3.2 — 컨테이너 app 유저의 GID 불일치

**증상**
`v0.3.1`로 배포 성공 후 브라우저 업로드 시 Django `PermissionError [Errno 13]: Permission denied: '/app/resources/origin'` 로 500.

**원인**
운영 호스트의 bind mount 대상 디렉토리(`resources/`)가 ACL로 관리되는 환경. 호스트 레벨에서 ACL은 `group:users` (GID 100) 멤버에게만 쓰기를 허용. 한편 `Dockerfile.prod`의 `useradd --create-home --uid 1000 app` 은 Linux의 user-private-group 관례대로 **GID 1000 (이름도 `app`)**을 함께 생성해 primary group으로 붙임. 결과적으로 컨테이너 프로세스는 GID 1000, ACL은 GID 100만 허용 → 권한 미스매치.

**해결 (`Dockerfile.prod`)**
- primary group을 호스트 ACL과 일치하는 GID 100 으로 지정
- 베이스 이미지에 `users` 그룹이 이미 있지만, 혹시 없을 때를 대비한 가드 포함
```
RUN (getent group 100 > /dev/null || groupadd --gid 100 users) \
 && useradd --create-home --uid 1000 --gid 100 app \
 && chown -R app:100 /app
```

**연결**
- Issue #10 / PR #11 / Tag `v0.3.2`
- 변경: `Dockerfile.prod` 1파일

**배운 점**
1. 컨테이너-호스트 bind mount는 **UID/GID 숫자가 양쪽에서 동일한 의미**여야 권한이 제대로 걸림. 이름이 아니라 숫자가 기준.
2. 호스트 측이 `chmod 777`처럼 보여도 ACL(`+` 플래그)이 덮어씌우면 모드 비트는 무력화됨. `getfacl` / ACL 도구로 진짜 권한을 확인해야 정확.
3. 진단 한 줄: `docker compose exec web id` 로 컨테이너 프로세스의 실제 UID/GID 확인 → 호스트 `ls -la` / ACL과 비교.

---

## 3. v0.3.3 — 프로덕션에서 `/media/` 서빙 누락

**증상**
- 채팅 UI 헤더 아이콘 자리가 깨짐 (`GET /media/icon/icon.png` → 404)
- 자료 출처 배지의 PDF 미리보기 모달이 열리지만 빈 창 (`GET /media/origin/*.pdf` → 404)

**원인**
`AI_Chat/urls.py` 에서 `/media/` URL 서빙이 `if settings.DEBUG:` 블록 안에만 등록되어 있었음. 운영은 `DEBUG=False` 라 이 분기가 실행되지 않아 `/media/*` 요청이 Django에 등록된 URL 패턴과 매치되지 않고 404.
- WhiteNoise는 `/static/*` 만 담당 — `/media/` 는 처리 안 함
- 운영 Compose에 별도 정적 파일 서버 없음 (DSM 레벨 역방향 프록시가 443 → gunicorn 으로 넘길 뿐)

**해결 (`AI_Chat/urls.py`)**
DEBUG 분기 제거하고 `django.views.static.serve` 를 `^media/` 에 무조건 등록:
```python
from django.views.static import serve
from django.urls import re_path

urlpatterns = [
    # ...
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]
```

**연결**
- Issue #12 / PR #13 / Tag `v0.3.3`
- 변경: `AI_Chat/urls.py` 1파일

**배운 점**
1. Django의 `static()` 헬퍼는 이름대로 정적파일 편의 함수지만 내부적으로 `DEBUG=True` 에서만 동작하게 되어 있어 프로덕션 이식성이 없음. `serve` 직접 등록이 환경 무관하게 동작.
2. 운영에서 `/media/` 서빙을 누가 책임질지 배포 초기 단계에서 명확히 해야 함. 옵션:
   - 앱 프로세스(gunicorn) 자체가 서빙 (현재 채택, 간단)
   - 앞단 nginx·CDN 이 정적 파일로 직접 서빙 (성능 좋음, 설정 복잡)
3. DEBUG 의존 코드 블록(`if settings.DEBUG:`)은 항상 "운영에서는 뭐가 빠지는가?" 를 점검.

---

## 4. 백머지 (PR #14)

**목적**
`v0.3.1`~`v0.3.3` hotfix 커밋은 `main`에 직접 올라가 있었고 `develop`에는 없음. 다음 정기 배포(develop → main) 때 hotfix 가 실수로 되돌아가는(revert) 상황 방지 차원에서 git-flow §2.4 절차대로 백머지.

**흐름**
```
main (v0.3.3 포함)  ──merge──▶  develop
```
- 3개의 머지 커밋 + 각 hotfix 커밋 총 6개가 develop으로 반영
- develop fast-forward 완료

**연결**
- PR #14 (base `develop`, head `main`)

**배운 점**
hotfix 패턴은 **"main에서 분기 → main으로 머지 → main을 develop으로 백머지"** 3단이 한 세트. 마지막 백머지를 놓치면 develop 에서 출발하는 다음 기능 작업이 이미 고쳐진 버그를 다시 건드릴 위험.

---

## 5. Phase 3 마무리

| 항목 | 상태 |
|---|---|
| Phase 3 마일스톤 | 닫힘 (7 이슈 전체 closed) |
| main 태그 | `v0.3.3` |
| develop HEAD | main과 동일 |
| 운영 상태 | 업로드·채팅·아이콘·PDF 미리보기 전부 정상 |

---

## 테스트/검증 체크리스트

- [x] `v0.3.1`: 배포 로그에서 `docker compose pull` 성공
- [x] `v0.3.2`: `docker compose exec web id` 결과에 `gid=100(users)` 확인, `touch /app/resources/origin/test` 성공
- [x] `v0.3.3`: 채팅 UI 아이콘 렌더, 대화 중 PDF 출처 클릭 → 모달에 문서 표시
- [x] PR #14: develop 이 main으로 fast-forward, 두 브랜치의 HEAD 동일
- [x] Phase 3 마일스톤 closed, 이슈 4·8·10·12 모두 done 라벨

---

## 번외 — 전반적 교훈

1. **"로컬에서 돈다 = 프로덕션에서도 돈다" 가 아님.** 특히 권한·경로·환경변수는 CI/운영 호스트에서 조용히 다름.
2. **첫 배포는 실패해도 좋게 설계할 것.** Actions 로그·`docker compose logs`·Django `DEBUG=True` 일시 토글 같은 진단 경로를 확보해두면 3분 안에 원인 판별 가능.
3. **한 핫픽스 = 한 PR = 한 태그** 원칙이 실전에서 매우 유용. 문제 하나씩 격리되어 롤백 지점도 명확하고 PR 리뷰도 집중됨.
4. **민감값은 코드와 문서 어디에도 하드코딩하지 않는다.** 모든 호스트·계정·경로는 Secrets 또는 플레이스홀더로. 이번에 한 번 값 흘리고 회수하느라 브랜치·PR 리셋까지 하는 비용 발생 — 처음부터 엄격히.
