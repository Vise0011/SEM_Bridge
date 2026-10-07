"""Conservative, deterministic draft extraction; never publishes rules."""

import re
from datetime import date

from sme_bridge.repositories.documents import DocumentRepository
from sme_bridge.rules import ApplicationPeriodRule, ApprovedRule, EmployeeCountRule, RegionRule
from sme_bridge.schemas.document import StoredPassage
from sme_bridge.schemas.management import ReviewSuggestions, RuleSuggestion
from sme_bridge.schemas.notice import NoticeSnapshot
from sme_bridge.schemas.publication import CitationInput

DATE = r"(20\d{2})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})\s*일?"
DATE_WINDOW = re.compile(DATE + r"\s*(?:~|∼|부터|–|-)\s*" + DATE)
EMPLOYEE = re.compile(
    r"(?:상시\s*(?:종업원|근로자|직원)|종업원|근로자)\s*(?:수|수가|수는|이)?\s*(\d{1,5})\s*명\s*(이하|미만|이상|초과)"
)
REGION = re.compile(
    r"본사.{0,16}(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)(?:특별자치시|특별자치도|특별시|광역시|도|시)?\s*(?:에\s*)?(?:소재|위치)"
)


async def current_passages(
    documents: DocumentRepository, notice: NoticeSnapshot
) -> list[StoredPassage]:
    current = await documents.current_hash(notice.notice_id, notice.version_hash)
    found: list[StoredPassage] = []
    # Legacy snapshots can contain multiple document hashes; only the current one is reviewed.
    for offset in range(0, 5000, 100):
        batch = await documents.search(
            notice_id=notice.notice_id, version_hash=notice.version_hash, limit=100, offset=offset
        )
        found.extend(p for p in batch if p.pdf_sha256 == current)
        if len(batch) < 100:
            return found
    raise ValueError("Too many historical passages; review with the local CLI")


def suggest_rules(notice: NoticeSnapshot, pages: list[StoredPassage]) -> ReviewSuggestions:
    suggestions: list[RuleSuggestion] = []
    seen: set[tuple[str, str]] = set()
    warnings = [
        "미검토 초안이며 조건 충족 판정에 사용되지 않습니다.",
        "표·예외·제외 대상·날짜의 시간 제한·업력 기준일은 자동 해석하지 않습니다.",
    ]
    for page in pages:
        if page.requires_ocr or page.security_flags:
            warnings.append(
                f"{page.page_number}번 위치는 OCR/보안 검토가 필요해 초안을 제외했습니다."
            )
            continue
        for line in page.text.splitlines():
            if (
                len(line.strip()) < 5
                or len(line) > 1000
                or any(w in line for w in ["제외", "예외", "단,", "단 "])
            ):
                continue
            evidence_id = f"{notice.notice_id}:{notice.version_hash}:draft-{len(suggestions) + 1}"
            rule: ApprovedRule | None = None
            if match := EMPLOYEE.search(line):
                value = int(match[1])
                operator = match[2]
                if operator == "미만" and value == 0:
                    continue
                rule = EmployeeCountRule(
                    minimum=value + (operator == "초과") if operator in {"이상", "초과"} else None,
                    maximum=value - (operator == "미만") if operator in {"이하", "미만"} else None,
                    evidence_id=evidence_id,
                )
            elif match := REGION.search(line):
                rule = RegionRule(allowed_regions=frozenset({match[1]}), evidence_id=evidence_id)
            elif any(word in line for word in ["신청", "접수"]) and (
                match := DATE_WINDOW.search(line)
            ):
                if re.search(r"\d\s*시|\d\s*분|\d\s*:\s*\d", line):
                    warnings.append(
                        "시간 제한이 있는 신청기간은 날짜 규칙으로 변환하지 않았습니다."
                    )
                    continue
                try:
                    rule = ApplicationPeriodRule(
                        starts_on=date(*map(int, match.groups()[:3])),
                        ends_on=date(*map(int, match.groups()[3:])),
                        evidence_id=evidence_id,
                    )
                except ValueError:
                    continue
            if rule is None or (rule.field, line) in seen:
                continue
            seen.add((rule.field, line))
            suggestions.append(
                RuleSuggestion(
                    rule=rule,
                    location_kind=page.location_kind,
                    citation=CitationInput(
                        evidence_id=evidence_id,
                        pdf_sha256=page.pdf_sha256,
                        page_number=page.page_number,
                        passage=line,
                    ),
                )
            )
            if len(suggestions) >= 100:
                break
        if len(suggestions) >= 100:
            break
    if not suggestions:
        warnings.append(
            "자동으로 표현할 수 있는 명확한 조건을 찾지 못했습니다. 수동 입력을 사용하세요."
        )
    return ReviewSuggestions(
        notice_id=notice.notice_id,
        version_hash=notice.version_hash,
        document_hash=pages[0].pdf_sha256 if pages else None,
        suggestions=suggestions,
        warnings=list(dict.fromkeys(warnings)),
    )
