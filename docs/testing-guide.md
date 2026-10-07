# 검증 결과와 직접 확인 가이드

## 현재 확인된 범위

2026-10-07 Windows / Python 3.12 환경에서 다음을 다시 실행했습니다.

- 자동 테스트: 로컬 152개 통과, PostgreSQL·Neo4j 연결이 없는 2개는 건너뜀
- Ruff 코드 검사·포맷 검사, mypy 소스 타입 검사, `pip check`, JavaScript 구문 검사 통과
- 실제 기업마당 API: 인증키로 읽기 전용 요청, 공고 5건 정상 응답
- 실제 로컬 HTTP 서버: 화면·Swagger·준비 상태·정적 파일, 공고와 원문 페이지 조회 확인
- 저장 데이터: 공고 30건, PDF 16건·365페이지, HWPX 13건·13섹션, OCR 검토 표시 7페이지
- 실제 관리 화면 재수집: PDF 16건은 중복 유지, HWPX 13건 신규 저장, HWP 1건은 변환 필요
- 데모 PASS·FAIL·UNKNOWN·신청기간 만료와 7개 인용, 결과 재조회, 재시도 키 및 충돌 검사
- 임시 SQLite DB: 빈 DB 시작, 잘못된 입력, 검색·페이지 분할·과거 버전, 승인 인용 검증,
  OCR 페이지 승인 거부, 승인 후 공고 변경 시 재검토 및 기존 결과 보존
- HWPX 확장 크기·압축률·XML 엔티티 제한, 문단 추출 및 섹션 위치 표시
- 관리 API 접근 제한, 미승인 초안·인용 검증, 수집 단일 실행·실패 메시지 비밀값 차단·중단 복구
- 고정 해시 OCR 모델 설치 검증, 실제 이미지 PDF OCR, 잘못된 페이지·시간 초과 시 자식 프로세스 종료
- 브라우저: 수집 요청·기록, 수동 조건 추가·원문 검증, 실제 미승인 JSON 다운로드 확인
- 실제 천안시 이미지 PDF의 한국어 OCR 참고 출력 확인 (오인식·잡음 존재, 승인 근거로 저장하지 않음)

위 개수는 특정 개발 시점의 기록입니다. 공고 수집이나 테스트 추가 후에는 달라집니다.
스모크 테스트는 **합성 기업 진단 결과를 로컬 DB에 추가 저장**합니다. 기존 결과는 삭제하지 않습니다.
승인 테스트는 pytest가 만든 임시 DB만 사용하고 실제 공고를 승인하지 않습니다.

이 PC에서는 Docker 명령/기본 설치 경로와 로컬 5432·7687 연결을 찾지 못했습니다.
기존 커밋 `c606bef`의 GitHub Actions에서는 84개 테스트 및 Docker 이미지 빌드가 통과했습니다.
추가 테스트를 포함한 CI는 PostgreSQL·Neo4j 통합 테스트와 Docker 내부 실행,
SQLite 컨테이너 재시작 후 결과 보존, PostgreSQL+Neo4j 컨테이너 API도 검사합니다.
새 실행의 완료 여부는 [GitHub Actions](https://github.com/Vise0011/SEM_Bridge/actions)에서 확인하세요.
구성된 검사와 실제 성공한 검사를 구분해야 합니다.

## 1. 기본 검사를 다시 실행하기

VS Code 터미널에서 프로젝트 폴더와 `(sembridge)` 환경인지 확인합니다.

```powershell
conda activate sembridge
python --version
(Get-Command python).Source
python -m pytest -q
python -m ruff check .
python -m ruff format --check src scripts tests
python -m mypy src
python -m pip check
```

Python 경로는 `anaconda3\envs\sembridge\python.exe`, 버전은 3.12여야 합니다.
테스트의 `skipped`는 성공한 검사 수에 포함하지 않습니다.
GitHub의 테스트용 임시 DB 연결 설정을 개인 `.env`에 그대로 복사하지 마세요.

## 2. 실행 중인 API 검사

서버가 꺼져 있다면 첫 번째 터미널에서 실행합니다.

```powershell
python scripts/run_local.py
```

두 번째 터미널에서 실행합니다.

```powershell
python scripts/smoke_api.py
python scripts/check_storage.py
python scripts/check_bizinfo.py
```

`smoke_api.py`가 오류 없이 끝나고 모든 항목에 OK가 표시되어야 합니다.
기업마당 검사는 네트워크가 필요합니다. 실패하면 인증키 길이를 임의로 바꾸지 말고,
키 설정과 네트워크를 확인한 뒤 `python scripts/diagnose_bizinfo.py`를 실행합니다.
키, `.env` 내용, 키가 포함된 요청 URL은 GitHub·메신저·스크린샷에 올리지 마세요.

## 3. 브라우저에서 직접 확인하기

[로컬 화면](http://127.0.0.1:8000/)에서 다음을 확인합니다.

1. 제목 검색에서 지역이나 사업명을 입력합니다. 검색 결과가 바뀌어야 합니다.
2. 없는 검색어는 빈 목록 안내를 보여야 합니다. 이전/다음으로 목록을 이동합니다.
3. 상세 및 근거 보기에서 공고 제목, 공식 링크, 공고 해시와 PDF 페이지를 확인합니다.
4. 원문 페이지 검색에서 실제 문구로 검색합니다. 이미지 PDF는 OCR 검토 표시를 확인합니다.
5. 진단 대상을 합성 공고 데모로 설정하고 기본 입력값으로 진단합니다.
   기준일 `2026-10-07`이면 7개 조건과 인용, 조건 충족 결과가 나와야 합니다.
6. 종업원 수를 11로 바꾸면 조건 불충족, 지역만 비우면 확인 필요가 나와야 합니다.
7. 결과 번호로 재조회하면 저장된 입력과 판정이 유지되어야 합니다.
8. 진단 대상을 공식 공고로 바꾸고 선택한 공식 공고만 진단합니다.
   승인하지 않은 공고는 자동으로 조건 충족 판정을 내리면 안 됩니다.

## 4. 실제 공식 공고의 사람 검토

기계 테스트는 **규칙이 원문의 정책적 의미를 올바르게 표현하는지** 보증하지 않습니다.
[조건 승인 가이드](review-guide.md)를 따라 텍스트가 추출되는 공고 1건부터 검토합니다.

1. 공식 공고기관의 원문과 첨부가 일치하는지 확인합니다.
2. 지역·업종·업력·신청기간 등 조건의 포함/미만 경계, 예외와 제외 대상을 확인합니다.
3. 조건마다 공고 버전, PDF 해시, 페이지 번호, 원문에 실제 존재하는 정확한 문장을 지정합니다.
4. 검토 파일은 `data/local/review.json`에 저장합니다. 이 폴더는 Git에서 제외됩니다.
5. 전체 조건 검토 전에는 `scope_complete=false`를 유지합니다.
6. 승인 명령을 실행하고 해당 공고만 지정해 합성 프로필로 결과를 비교합니다.

```powershell
python scripts/approve_program.py data/local/review.json --backend sqlite
```

원문과 정확히 대응하지 않는 조건은 승인하지 마세요. 이미지 PDF·바이너리 HWP 또는
지원하지 않는 세부 조건은 별도 구현과 검토가 필요합니다. 최종 자격은 공고기관에 확인합니다.

## 5. Docker 환경 직접 확인하기

Docker Desktop 설치 여부와 실행 상태를 먼저 확인합니다. 기존 `.env`를 덮어쓰지 말고
PostgreSQL·Neo4j 비밀번호가 설정되었는지 확인합니다. 이미 실행 중인 로컬 API가 있으면
그 서버 터미널에서 Ctrl+C로 종료하여 8000번 포트가 겹치지 않게 합니다.

```powershell
docker version
docker compose config --quiet
docker compose up --build -d
docker compose ps
python scripts/smoke_api.py
```

Docker 모드는 별도의 PostgreSQL 저장소를 사용합니다. SQLite 공고가 자동 복사되지 않으므로
처음에는 공식 공고가 0건이어도 정상입니다. 수집이 필요하면 다음을 실행합니다.

```powershell
docker compose exec api python scripts/ingest_bizinfo.py --count 30 --documents
```

API 준비 상태가 ready이고 PostgreSQL·Neo4j가 healthy여야 합니다.
`docker compose config`에 `--quiet`를 빼면 비밀번호가 표시될 수 있으므로 결과를 공유하지 마세요.
종료는 `docker compose stop`을 사용합니다. 볼륨 삭제 명령은 데이터 보존을 위해 사용하지 않습니다.

## 아직 검증할 수 없는 항목

- 바이너리 HWP·표 레이아웃 복원과 LLM 자동 추출: 아직 미구현
- 공식 조건의 해석 정확도: 검토한 실제 공고와 정답 프로필 데이터셋이 필요함
- 대규모 성능·검색 정확도: 목표 동시 사용자, 데이터 규모, 정답셋과 허용 기준이 필요함
- 공개 운영 보안: 로그인·권한·요청 제한·백업·TLS 설계가 필요함

현재 앱은 개인 로컬 개발용입니다. 실제 기업의 민감 정보를 입력하거나 그대로 공개 배포하지 마세요.
