# SEM Bridge

[![Checks](https://github.com/Vise0011/SEM_Bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/Vise0011/SEM_Bridge/actions/workflows/ci.yml)

기업마당 금융 지원사업을 수집하고, 합성 기업 프로필과 **사람이 검토한 조건**을 비교하는 Python 3.12 프로젝트입니다.
공고의 조건을 충족하면 `PASS`, 벗어나면 `FAIL`, 정보·근거·검토가 부족하면 `UNKNOWN`을 반환합니다.
최종 신청 자격은 공고기관에서 확인해야 합니다.

현재는 **개인 로컬 개발용**입니다. 사용자 인증·권한 관리·요청 제한은 구현하지 않았으므로
공개 서버에 그대로 배포하거나 실제 기업의 민감 정보를 입력하지 마세요.
Docker의 API·데이터베이스 포트도 로컬 주소에만 연결합니다.

## 구현된 기능

- 기업마당 공식 API 클라이언트: 실제 배열 응답과 레거시 객체 응답 지원, 제한된 재시도
- 공고 내용의 SHA-256 버전 관리와 중복 수집 방지
- 공식 HTTPS 도메인만 사용하는 PDF/HWPX 다운로드: 리다이렉트 검증, 크기·위치 수 제한
- 페이지별 텍스트·PDF 해시·OCR 필요 여부·의심 문구 표시
- 공고 목록·제목 검색·상세·과거 버전·원문 페이지 검색 API
- 지역·인원·업력·신청기간·업종·매출 구간·자금 목적·인증의 결정적 규칙 판정
- JSON 파일을 통한 수동 조건 승인: 정확한 페이지 인용 및 현재 공고/PDF 버전 검증
- 검토 범위가 일부이면 전체 결과는 `UNKNOWN`; 공고/PDF 변경 시 기존 승인은 검색에서 제외
- 공식 공고와 합성 데모 구분, 결과 저장·재조회, 동시 요청의 재시도 키 처리
- FastAPI 웹 화면 및 Swagger, 로컬 SQLite 또는 PostgreSQL 저장, Neo4j 합성 데모 그래프
- 로컬 관리 화면: 제한된 수집 작업·첨부 재수집·진행 기록·서버 재시작 시 중단 복구
- 지역·인원·신청기간의 보수적인 미승인 초안, 8개 조건 수동 검토 및 원문 검증 JSON 다운로드
- HWPX 문단 추출 (실제 페이지가 아닌 섹션 위치로 표시), 제한된 별도 프로세스의 한국어·영어 OCR 미리보기
- GitHub Actions: lint·format·type·단위/통합 테스트와 Docker 이미지 빌드

LLM, LangGraph, MCP 서버, 벡터 검색, 바이너리 HWP 파싱, 공인 평가 데이터셋은 아직 구현하지 않았습니다.
원문 검색은 페이지 텍스트의 부분문자열 검색입니다. 공식 승인 조건은 SQL 저장소에 보관하고,
PostgreSQL 실행 모드의 Neo4j는 합성 데모 후보 검색에 사용합니다.

## Windows / Anaconda 빠른 실행

프로젝트 폴더에서 `(sembridge)` 환경으로 실행합니다.

```powershell
conda activate sembridge
python -m pip install -e ".[dev]"
Copy-Item .env.example .env  # .env가 없을 때만 실행
```

기존 `.env`는 덮어쓰지 마세요. 공식 공고 수집이 필요하면 `.env`에 발급된 인증키를 저장합니다.

```dotenv
BIZINFO_API_KEY=발급받은키
```

인증키의 길이를 임의로 제한하지 않습니다. 인증키 발급: [기업마당 공식 안내](https://www.bizinfo.go.kr/apiDetail.do?id=bizinfoApi).
`.env`, 로컬 DB, 수집된 원문은 Git과 Docker 빌드 대상에서 제외됩니다.

Docker 없이 영구 저장 가능한 로컬 모드:

```powershell
python scripts/check_bizinfo.py
python scripts/ingest_bizinfo.py --backend sqlite --count 30 --documents
python scripts/run_local.py
```

- 웹 화면: <http://127.0.0.1:8000/>
- Swagger: <http://127.0.0.1:8000/docs>
- 저장 위치: `data/local/bridge.sqlite3`
- 종료: 서버 터미널에서 `Ctrl+C`
- API 키가 없어도 웹 화면과 합성 데모는 실행할 수 있습니다.

HWP 등 미지원 첨부는 `FORMAT_CONVERSION_REQUIRED`로 건너뜁니다.
수집 결과가 `STORED`라고 해도 조건이 승인되는 것은 아닙니다.
다시 수집하면 변경된 공고/PDF만 추가 저장하고 기존 버전은 유지합니다.

`run_local.py`는 로컬 관리 화면을 활성화합니다. `--read-only`로 수집·검토 도구를 끌 수 있습니다.
관리 API는 루프백 주소·클라이언트·동일 출처와 프로세스별 토큰을 확인하며 승인 자체는 제공하지 않습니다.
여전히 공개 배포용 사용자 인증이 아니므로 공개 서버로 노출하지 마세요. 동일 DB로 관리 서버를 여러 개 실행하지 마세요.

OCR을 사용할 때 한 번만 실행합니다 (공식 모델 약 6MB, 프로젝트 내부 저장):

```powershell
python scripts/setup_ocr.py
```

이후 웹 화면을 새로고침합니다. OCR은 한 번에 PDF 1~3페이지, 60초 제한이며 결과는 참고용입니다.
원문을 덮어쓰거나 OCR 문장을 승인 근거로 등록하지 않습니다. [문서·OCR 가이드](docs/document-guide.md)를 참고하세요.

## Docker / PostgreSQL + Neo4j

`.env`의 PostgreSQL·Neo4j 비밀번호를 설정한 뒤:

```powershell
docker compose up --build -d
docker compose exec api python scripts/ingest_bizinfo.py --count 30 --documents
```

API는 로컬 8000번 포트입니다. Docker가 API 포트를 쓰고 있다면 `run_local.py`를 같은 포트에서 실행하지 마세요.
호스트에서 PostgreSQL 모드로 실행할 경우 `python scripts/run_local.py --backend postgres`를 사용합니다.
SQLite와 PostgreSQL은 별도 데이터 저장소이므로 수집/승인 명령의 `--backend`를 맞춰야 합니다.

## API

| 요청 | 동작 |
|---|---|
| `GET /health` | 프로세스 확인 |
| `GET /ready` | 저장소 조회 가능 여부 |
| `GET /v1/notices?q=대전&limit=30&offset=0` | 현재 공고 제목 검색 |
| `GET /v1/notices/{id}` | 공고 상세, `version`으로 과거 버전 지정 가능 |
| `GET /v1/notices/{id}/versions` | 저장된 공고 버전, 최대 100개 |
| `GET /v1/notices/{id}/passages?q=지원대상` | 페이지 근거 검색, `version`, `limit`, `offset` 지원 |
| `POST /v1/cases?source=official` | 승인된 공식 조건 진단, 미승인 공고는 확인 필요 |
| `POST /v1/cases?source=official&notice_id={id}` | 지정한 공식 공고 진단 |
| `POST /v1/cases?source=demo` | 합성 데모 진단 |
| `GET /v1/cases/{case_id}` | 저장된 결과 재조회 |
| `GET /v1/manage/status` | 로컬 관리 활성화·OCR 준비 및 로컬 세션 토큰 |
| `GET /v1/manage/jobs` / `POST /v1/manage/jobs` | 수집 기록 / 제한된 수집 작업 시작 |
| `GET /v1/manage/notices/{id}/suggestions` | 원문에 묶인 미승인 초안 |
| `POST /v1/manage/review/validate` | 인용 검증만 수행, 승인 등록하지 않음 |
| `POST /v1/manage/notices/{id}/ocr` | 현재 PDF 해시 확인 후 참고 OCR |

공식 기본 모드에서 미승인 공고를 포함한 후보는 메타데이터로 고릅니다.
지역 해시태그는 탐색 순위에만 사용하며 자격 조건으로 자동 승인하지 않습니다.
같은 요청을 재시도할 때 `Idempotency-Key` 헤더를 사용하면 동일 결과를 반환합니다.
같은 키에 다른 입력을 보내면 HTTP 409입니다. 키 없이 보내는 요청은 각각 새 결과입니다.

```json
{
  "business_type": "CORPORATION",
  "established_date": "2023-03-15",
  "hq_region": "대전",
  "industry_code": "J62",
  "employee_count": 8,
  "annual_sales_band": "UNDER_1B_KRW",
  "certifications": [],
  "funding_purpose": "WORKING_CAPITAL",
  "query_date": "2026-10-07"
}
```

## 공식 공고 조건 승인

[승인 절차와 JSON 형식](docs/review-guide.md)을 참고하세요.
검토자는 조건의 의미를 확인하고 정확한 PDF 문장·페이지·해시를 지정합니다.
웹에서 공고를 선택하고 초안을 입력 양식으로 가져오거나 수동 입력한 뒤 검토 파일을 내려받을 수 있습니다.
HWPX의 `page_number`는 실제 페이지 번호가 아닌 화면에 표시된 섹션 인덱스입니다.
CLI는 인용이 존재하는지 검증하지만 자연어의 법적·정책적 의미를 대신 검토하지 않습니다.

```powershell
python scripts/approve_program.py data/local/review.json --backend sqlite
```

일부 조건만 확인한 파일은 `scope_complete=false`를 유지하세요.
공고가 바뀌거나 PDF가 교체되면 다시 수집·검토해야 합니다.

## 검증

```powershell
python -m pytest -q
python -m ruff check .
python -m ruff format --check src scripts tests
python -m mypy src
python scripts/smoke_api.py
```

테스트는 공식 API 키를 사용하지 않습니다. SQLite 통합 테스트는 임시 DB에서 실행합니다.
PostgreSQL·Neo4j 통합 테스트는 CI의 임시 서비스 또는 명시적인 테스트 연결 설정이 있을 때 실행하며,
연결 설정이 없으면 건너뜁니다. PostgreSQL 테스트는 임시 스키마를 생성하고 종료 시 해당 스키마만 제거합니다.
실행한 환경 및 제약은 [시스템 카드](docs/system-card.md)에 기록합니다.
실행 결과와 직접 확인 순서는 [테스트 가이드](docs/testing-guide.md)를 참고하세요.

초기 목표 아키텍처는 [기획 문서](SME_Bridge_README.md)에 보존했습니다. 기획 문서의 수치·목표는 구현 결과가 아닙니다.
