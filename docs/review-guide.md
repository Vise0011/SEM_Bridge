# 공식 조건 검토·승인

웹 화면에서 공고를 선택하고 PDF 페이지 또는 HWPX 섹션을 확인합니다.
공고 상세의 `version_hash`와 페이지의 `pdf_sha256`를 사용합니다.
HWP, OCR 필요 위치, 의심 문구가 있는 위치는 승인 근거로 사용할 수 없습니다.
HWPX의 `page_number`는 표시된 섹션 인덱스이며 실제 페이지 번호가 아닙니다.

## 웹 검토 절차

1. `python scripts/run_local.py`로 서버를 실행하고 공고 상세를 엽니다.
2. 자동 초안의 문장을 원문과 대조한 뒤 '입력 양식으로 가져오기'로 편집합니다.
   자동 초안은 지역·인원·신청기간만 보수적으로 제안하며, 표·예외·시간 제한 등은 해석하지 않습니다.
3. 수동 입력도 가능합니다. 원문 위치를 선택하고 정확한 문장을 복사해 검토 목록에 추가합니다.
4. 검토자 식별명을 입력하고 원문 대조 확인을 체크합니다. 전체 범위 확인은 모든 조건을 검토한 경우에만 체크합니다.
5. '원문 검증 후 검토 파일 다운로드'를 누릅니다. 다운로드만으로 승인되지 않습니다.
6. 내려받은 파일을 `data/local/review.json`에 저장하고 아래 명령으로 명시적으로 등록합니다.

```powershell
python scripts/approve_program.py data/local/review.json --backend sqlite
```

서버는 인용 존재 여부를 확인할 뿐, 문장의 의미와 조건 값의 대응을 보장하지 않습니다.
화면을 다시 열거나 수집 작업이 완료되면 편집 중 초안은 초기화됩니다. 먼저 파일을 내려받으세요.
초안·OCR 문장은 문서 데이터이며 도구 실행이나 키 제출 같은 지시로 받아들이면 안 됩니다.

## 수동 JSON 형식

아래는 형식 예시이며 실제 공고의 조건이 아닙니다.
자리표시자·문장·값을 실제 검토한 내용으로 교체하고 `data/local/review.json`에 저장합니다.

```json
{
  "notice_id": "PBLN_공고ID",
  "version_hash": "64자리_공고_SHA256",
  "approved_by": "local-reviewer",
  "scope_complete": false,
  "conditions": [
    {
      "field": "hq_region",
      "allowed_regions": ["대전"],
      "evidence_id": "PBLN_공고ID:64자리_공고_SHA256:region"
    }
  ],
  "citations": [
    {
      "evidence_id": "PBLN_공고ID:64자리_공고_SHA256:region",
      "pdf_sha256": "64자리_PDF_SHA256",
      "page_number": 1,
      "passage": "저장된 PDF에 실제로 존재하는 정확한 문장을 입력합니다."
    }
  ]
}
```

인용 ID는 `공고ID:공고버전해시:임의고유이름` 형식으로 작성합니다.
조건이 참조하는 모든 인용이 필요합니다. PDF 해시와 페이지, 문장 중 하나라도 불일치하면 승인되지 않습니다.
게시 직전에도 최신 공고·PDF가 바뀌지 않았는지 저장소 트랜잭션에서 재확인합니다.

| field | 조건 필드 |
|---|---|
| hq_region | allowed_regions: 지역 문자열 목록 |
| employee_count | minimum / maximum: 포함되는 정수 경계, 하나 이상 |
| business_age_years | minimum / maximum: 판정 기준일의 만 업력, 하나 이상 |
| query_date | starts_on / ends_on: YYYY-MM-DD 신청기간, 양쪽 날짜 포함 |
| industry_code | allowed_codes: 정확한 업종 코드 목록 |
| annual_sales_band | allowed_bands: UNDER_1B_KRW / FROM_1B_TO_5B_KRW / OVER_5B_KRW |
| funding_purpose | allowed_purposes: WORKING_CAPITAL / FACILITY_CAPITAL / BOTH |
| certifications | required_any_of: 하나 이상 갖춰야 하는 인증 목록 |

조건 표현이 정확하게 대응되지 않으면 승인하지 마세요. 예를 들어 공고일 기준의 업력을
판정일 기준 업력으로 바꾸거나, 3년 미만을 3년 이하로 바꾸면 안 됩니다.
현재 규칙이 표현하지 못하는 세부 자격은 추가 검토가 필요합니다.

`scope_complete=true`는 공고의 전체 자격 조건을 지원되는 규칙으로 검토한 경우에만 설정합니다.
부분 검토는 개별 조건 결과를 보여주되 전체 PASS를 내지 않습니다.
승인자는 개인 식별정보 대신 로컬 별칭을 사용할 수 있습니다.
승인 API는 외부에 제공하지 않고 로컬 명령으로만 실행합니다.
