"""Neo4j repository for support programs and approved conditions."""

from datetime import date
from typing import Protocol

from neo4j import AsyncDriver

from sme_bridge.rules import (
    AnnualSalesRule,
    ApplicationPeriodRule,
    BusinessAgeRule,
    CertificationRule,
    EmployeeCountRule,
    FundingPurposeRule,
    IndustryRule,
    RegionRule,
    full_years_between,
)
from sme_bridge.schemas.evidence import EvidenceReference, SourceKind
from sme_bridge.schemas.profile import BusinessProfile
from sme_bridge.schemas.program import ProgramDefinition

PROGRAM_CONSTRAINT = """
CREATE CONSTRAINT program_id_unique IF NOT EXISTS
FOR (program:Program) REQUIRE program.program_id IS UNIQUE
"""

CONDITION_CONSTRAINT = """
CREATE CONSTRAINT condition_id_unique IF NOT EXISTS
FOR (condition:Condition) REQUIRE condition.condition_id IS UNIQUE
"""

EVIDENCE_CONSTRAINT = """
CREATE CONSTRAINT evidence_id_unique IF NOT EXISTS
FOR (evidence:Evidence) REQUIRE evidence.evidence_id IS UNIQUE
"""

SEED_DEMO_PROGRAM = """
MERGE (program:Program {program_id: $program_id})
SET program.title = $title,
    program.approved = true

MERGE (region:Condition {condition_id: $region_condition_id})
SET region.field = 'hq_region',
    region.operator = 'IN',
    region.expected_strings = $allowed_regions,
    region.evidence_id = $region_evidence_id,
    region.approved = true
MERGE (program)-[:HAS_CONDITION]->(region)

MERGE (employees:Condition {condition_id: $employee_condition_id})
SET employees.field = 'employee_count',
    employees.operator = 'LTE',
    employees.expected_integer = $maximum_employees,
    employees.evidence_id = $employee_evidence_id,
    employees.approved = true
MERGE (program)-[:HAS_CONDITION]->(employees)

MERGE (age:Condition {condition_id: $age_condition_id})
SET age.field = 'business_age_years',
    age.operator = 'BETWEEN',
    age.minimum_integer = $minimum_business_age,
    age.maximum_integer = $maximum_business_age,
    age.evidence_id = $age_evidence_id,
    age.approved = true
MERGE (program)-[:HAS_CONDITION]->(age)

MERGE (period:Condition {condition_id: $period_condition_id})
SET period.field = 'query_date',
    period.operator = 'BETWEEN_DATES',
    period.starts_on = $starts_on,
    period.ends_on = $ends_on,
    period.evidence_id = $period_evidence_id,
    period.approved = true
MERGE (program)-[:HAS_CONDITION]->(period)

MERGE (industry:Condition {condition_id: $industry_condition_id})
SET industry.field = 'industry_code',
    industry.operator = 'IN',
    industry.expected_strings = $allowed_industries,
    industry.evidence_id = $industry_evidence_id,
    industry.approved = true
MERGE (program)-[:HAS_CONDITION]->(industry)

MERGE (sales:Condition {condition_id: $sales_condition_id})
SET sales.field = 'annual_sales_band',
    sales.operator = 'IN',
    sales.expected_strings = $allowed_sales_bands,
    sales.evidence_id = $sales_evidence_id,
    sales.approved = true
MERGE (program)-[:HAS_CONDITION]->(sales)

MERGE (funding:Condition {condition_id: $funding_condition_id})
SET funding.field = 'funding_purpose',
    funding.operator = 'IN',
    funding.expected_strings = $allowed_funding_purposes,
    funding.evidence_id = $funding_evidence_id,
    funding.approved = true
MERGE (program)-[:HAS_CONDITION]->(funding)
"""

SEED_DEMO_EVIDENCE = """
UNWIND $items AS item
MATCH (condition:Condition {evidence_id: item.evidence_id})
MERGE (evidence:Evidence {evidence_id: item.evidence_id})
SET evidence.passage = item.passage,
    evidence.page = item.page,
    evidence.source_url = item.source_url,
    evidence.notice_version = item.notice_version,
    evidence.source_kind = item.source_kind
MERGE (condition)-[:SUPPORTED_BY]->(evidence)
"""

FIND_EVIDENCE = """
UNWIND $evidence_ids AS evidence_id
MATCH (evidence:Evidence {evidence_id: evidence_id})
RETURN evidence.evidence_id AS evidence_id,
       evidence.passage AS passage,
       evidence.page AS page,
       evidence.source_url AS source_url,
       evidence.notice_version AS notice_version,
       evidence.source_kind AS source_kind
ORDER BY evidence.evidence_id
"""

FIND_APPROVED_PROGRAMS = """
MATCH (program:Program)-[:HAS_CONDITION]->(condition:Condition)
WHERE program.approved = true AND condition.approved = true
RETURN program.program_id AS program_id,
       program.title AS title,
       collect(condition {
           .field,
           .operator,
           .expected_strings,
           .expected_integer,
           .minimum_integer,
           .maximum_integer,
           .starts_on,
           .ends_on,
           .evidence_id
       }) AS conditions
ORDER BY program.program_id
"""

FIND_CANDIDATES = """
MATCH (program:Program)-[:HAS_CONDITION]->(condition:Condition)
WHERE program.approved = true AND condition.approved = true
WITH program, collect(condition) AS conditions
WITH program, conditions,
     reduce(score = 0, condition IN conditions |
         score + CASE
             WHEN $hq_region IS NOT NULL
                  AND condition.field = 'hq_region'
                  AND $hq_region IN condition.expected_strings THEN 1
             WHEN $employee_count IS NOT NULL
                  AND condition.field = 'employee_count'
                  AND condition.operator = 'LTE'
                  AND $employee_count <= condition.expected_integer THEN 1
             WHEN $industry_code IS NOT NULL
                  AND condition.field = 'industry_code'
                  AND $industry_code IN condition.expected_strings THEN 1
             WHEN $annual_sales_band IS NOT NULL
                  AND condition.field = 'annual_sales_band'
                  AND $annual_sales_band IN condition.expected_strings THEN 1
             WHEN $funding_purpose IS NOT NULL
                  AND condition.field = 'funding_purpose'
                  AND $funding_purpose IN condition.expected_strings THEN 1
             ELSE 0
         END
     ) AS score
RETURN program.program_id AS program_id,
       program.title AS title,
       [condition IN conditions | condition {
           .field,
           .operator,
           .expected_strings,
           .expected_integer,
           .minimum_integer,
           .maximum_integer,
           .starts_on,
           .ends_on,
           .evidence_id
       }] AS conditions,
       score
ORDER BY score DESC, program.program_id ASC
LIMIT $limit
"""


class ProgramRepository(Protocol):
    """Read boundary for published program conditions."""

    async def find_approved(self) -> list[ProgramDefinition]:
        """Return only programs and conditions approved for evaluation."""
        ...

    async def find_candidates(
        self,
        profile: BusinessProfile,
        limit: int = 3,
    ) -> list[ProgramDefinition]:
        """Return the best-matching approved programs in deterministic order."""
        ...

    async def find_evidence(self, evidence_ids: list[str]) -> list[EvidenceReference]:
        """Return citation metadata for the requested evidence identifiers."""
        ...


class InMemoryProgramRepository:
    """Program repository used in isolated unit tests."""

    def __init__(
        self,
        programs: list[ProgramDefinition],
        evidence: list[EvidenceReference] | None = None,
    ) -> None:
        self._programs = programs
        self._evidence = {
            item.evidence_id: item for item in evidence or self._default_evidence(programs)
        }

    async def find_approved(self) -> list[ProgramDefinition]:
        return list(self._programs)

    async def find_candidates(
        self,
        profile: BusinessProfile,
        limit: int = 3,
    ) -> list[ProgramDefinition]:
        ranked = sorted(
            self._programs,
            key=lambda program: (-self._score(profile, program), program.program_id),
        )
        return ranked[:limit]

    async def find_evidence(self, evidence_ids: list[str]) -> list[EvidenceReference]:
        return [self._evidence[item] for item in evidence_ids if item in self._evidence]

    @staticmethod
    def _default_evidence(programs: list[ProgramDefinition]) -> list[EvidenceReference]:
        evidence_ids = {
            condition.evidence_id for program in programs for condition in program.conditions
        }
        return [
            EvidenceReference(
                evidence_id=evidence_id,
                passage="단위 테스트용 승인 조건 근거",
                page=1,
                source_url=None,
                notice_version="sha256:test",
                source_kind=SourceKind.SYNTHETIC_DEMO,
            )
            for evidence_id in sorted(evidence_ids)
        ]

    @staticmethod
    def _score(profile: BusinessProfile, program: ProgramDefinition) -> int:
        score = 0
        for condition in program.conditions:
            if isinstance(condition, RegionRule):
                if profile.hq_region is not None and profile.hq_region in condition.allowed_regions:
                    score += 1
            elif isinstance(condition, EmployeeCountRule) and profile.employee_count is not None:
                above_minimum = (
                    condition.minimum is None or profile.employee_count >= condition.minimum
                )
                below_maximum = (
                    condition.maximum is None or profile.employee_count <= condition.maximum
                )
                if above_minimum and below_maximum:
                    score += 1
            elif isinstance(condition, BusinessAgeRule) and profile.established_date is not None:
                age = full_years_between(profile.established_date, profile.query_date)
                above_minimum = condition.minimum is None or age >= condition.minimum
                below_maximum = condition.maximum is None or age <= condition.maximum
                if above_minimum and below_maximum:
                    score += 1
            elif isinstance(condition, ApplicationPeriodRule):
                if condition.starts_on <= profile.query_date <= condition.ends_on:
                    score += 1
            elif isinstance(condition, IndustryRule):
                if (
                    profile.industry_code is not None
                    and profile.industry_code in condition.allowed_codes
                ):
                    score += 1
            elif isinstance(condition, AnnualSalesRule):
                if (
                    profile.annual_sales_band is not None
                    and profile.annual_sales_band.value in condition.allowed_bands
                ):
                    score += 1
            elif isinstance(condition, FundingPurposeRule):
                if (
                    profile.funding_purpose is not None
                    and profile.funding_purpose.value in condition.allowed_purposes
                ):
                    score += 1
            elif isinstance(condition, CertificationRule):
                if profile.certifications is not None and (
                    set(profile.certifications) & condition.required_any_of
                ):
                    score += 1
        return score


class Neo4jProgramRepository:
    """Stores approved program conditions as a queryable graph."""

    def __init__(self, driver: AsyncDriver) -> None:
        self._driver = driver

    async def ensure_schema(self) -> None:
        async with self._driver.session(database="neo4j") as session:
            program_result = await session.run(PROGRAM_CONSTRAINT)
            await program_result.consume()
            condition_result = await session.run(CONDITION_CONSTRAINT)
            await condition_result.consume()
            evidence_result = await session.run(EVIDENCE_CONSTRAINT)
            await evidence_result.consume()

    async def seed_demo_program(self) -> None:
        """Upsert the approved demo program without creating duplicates."""
        async with self._driver.session(database="neo4j") as session:
            result = await session.run(
                SEED_DEMO_PROGRAM,
                program_id="PBLN_DEMO",
                title="대전 소기업 운전자금 데모",
                region_condition_id="COND-DEMO-REGION",
                allowed_regions=["대전"],
                region_evidence_id="EV-DEMO-REGION",
                employee_condition_id="COND-DEMO-EMPLOYEE",
                maximum_employees=10,
                employee_evidence_id="EV-DEMO-EMPLOYEE",
                age_condition_id="COND-DEMO-AGE",
                minimum_business_age=0,
                maximum_business_age=7,
                age_evidence_id="EV-DEMO-AGE",
                period_condition_id="COND-DEMO-PERIOD",
                starts_on="2026-01-01",
                ends_on="2026-12-31",
                period_evidence_id="EV-DEMO-PERIOD",
                industry_condition_id="COND-DEMO-INDUSTRY",
                allowed_industries=["J62"],
                industry_evidence_id="EV-DEMO-INDUSTRY",
                sales_condition_id="COND-DEMO-SALES",
                allowed_sales_bands=["UNDER_1B_KRW"],
                sales_evidence_id="EV-DEMO-SALES",
                funding_condition_id="COND-DEMO-FUNDING",
                allowed_funding_purposes=["WORKING_CAPITAL", "BOTH"],
                funding_evidence_id="EV-DEMO-FUNDING",
            )
            await result.consume()

        await self._seed_demo_evidence()

    async def _seed_demo_evidence(self) -> None:
        items = [
            ("EV-DEMO-REGION", "본사가 대전광역시에 소재한 기업", 1),
            ("EV-DEMO-EMPLOYEE", "상시 종업원 수가 10명 이하인 기업", 1),
            ("EV-DEMO-AGE", "판정 기준일 기준 업력 7년 이하인 기업", 2),
            ("EV-DEMO-PERIOD", "신청기간: 2026년 1월 1일부터 12월 31일까지", 2),
            ("EV-DEMO-INDUSTRY", "지원 업종 코드: J62", 3),
            ("EV-DEMO-SALES", "연 매출 10억원 미만 기업", 3),
            ("EV-DEMO-FUNDING", "운전자금 또는 운전·시설 복합자금 지원", 4),
        ]
        payload = [
            {
                "evidence_id": evidence_id,
                "passage": passage,
                "page": page,
                "source_url": None,
                "notice_version": "sha256:synthetic-demo-v1",
                "source_kind": "SYNTHETIC_DEMO",
            }
            for evidence_id, passage, page in items
        ]
        async with self._driver.session(database="neo4j") as session:
            result = await session.run(SEED_DEMO_EVIDENCE, items=payload)
            await result.consume()

    async def count_programs(self) -> int:
        async with self._driver.session(database="neo4j") as session:
            result = await session.run("MATCH (program:Program) RETURN count(program) AS count")
            record = await result.single()
        return 0 if record is None else int(record["count"])

    async def find_approved(self) -> list[ProgramDefinition]:
        async with self._driver.session(database="neo4j") as session:
            result = await session.run(FIND_APPROVED_PROGRAMS)
            records = await result.data()

        programs: list[ProgramDefinition] = []
        for record in records:
            conditions = [self._parse_condition(condition) for condition in record["conditions"]]
            programs.append(
                ProgramDefinition(
                    program_id=record["program_id"],
                    title=record["title"],
                    conditions=conditions,
                )
            )
        return programs

    async def find_candidates(
        self,
        profile: BusinessProfile,
        limit: int = 3,
    ) -> list[ProgramDefinition]:
        async with self._driver.session(database="neo4j") as session:
            result = await session.run(
                FIND_CANDIDATES,
                hq_region=profile.hq_region,
                employee_count=profile.employee_count,
                industry_code=profile.industry_code,
                annual_sales_band=(
                    None if profile.annual_sales_band is None else profile.annual_sales_band.value
                ),
                funding_purpose=(
                    None if profile.funding_purpose is None else profile.funding_purpose.value
                ),
                limit=limit,
            )
            records = await result.data()

        programs: list[ProgramDefinition] = []
        for record in records:
            conditions = [self._parse_condition(condition) for condition in record["conditions"]]
            programs.append(
                ProgramDefinition(
                    program_id=record["program_id"],
                    title=record["title"],
                    conditions=conditions,
                )
            )
        return programs

    async def find_evidence(self, evidence_ids: list[str]) -> list[EvidenceReference]:
        if not evidence_ids:
            return []
        async with self._driver.session(database="neo4j") as session:
            result = await session.run(FIND_EVIDENCE, evidence_ids=evidence_ids)
            records = await result.data()
        return [EvidenceReference.model_validate(record) for record in records]

    @staticmethod
    def _parse_condition(
        condition: dict[str, object],
    ) -> (
        RegionRule
        | EmployeeCountRule
        | BusinessAgeRule
        | ApplicationPeriodRule
        | IndustryRule
        | AnnualSalesRule
        | FundingPurposeRule
        | CertificationRule
    ):
        field = condition.get("field")
        operator = condition.get("operator")
        evidence_id = str(condition.get("evidence_id", ""))

        if field == "hq_region" and operator == "IN":
            values = condition.get("expected_strings")
            if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                raise ValueError("invalid approved region condition")
            return RegionRule(
                allowed_regions=frozenset(values),
                evidence_id=evidence_id,
            )

        if field == "employee_count" and operator == "LTE":
            maximum = condition.get("expected_integer")
            if not isinstance(maximum, int):
                raise ValueError("invalid approved employee-count condition")
            return EmployeeCountRule(maximum=maximum, evidence_id=evidence_id)

        if field == "business_age_years" and operator == "BETWEEN":
            minimum = condition.get("minimum_integer")
            maximum = condition.get("maximum_integer")
            if not isinstance(minimum, int) or not isinstance(maximum, int):
                raise ValueError("invalid approved business-age condition")
            return BusinessAgeRule(
                minimum=minimum,
                maximum=maximum,
                evidence_id=evidence_id,
            )

        if field == "query_date" and operator == "BETWEEN_DATES":
            starts_on = condition.get("starts_on")
            ends_on = condition.get("ends_on")
            if not isinstance(starts_on, str) or not isinstance(ends_on, str):
                raise ValueError("invalid approved application-period condition")
            return ApplicationPeriodRule(
                starts_on=date.fromisoformat(starts_on),
                ends_on=date.fromisoformat(ends_on),
                evidence_id=evidence_id,
            )

        if field == "industry_code" and operator == "IN":
            values = condition.get("expected_strings")
            if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                raise ValueError("invalid approved industry condition")
            return IndustryRule(allowed_codes=frozenset(values), evidence_id=evidence_id)

        if field == "annual_sales_band" and operator == "IN":
            values = condition.get("expected_strings")
            if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                raise ValueError("invalid approved sales-band condition")
            return AnnualSalesRule(allowed_bands=frozenset(values), evidence_id=evidence_id)

        if field == "funding_purpose" and operator == "IN":
            values = condition.get("expected_strings")
            if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                raise ValueError("invalid approved funding-purpose condition")
            return FundingPurposeRule(
                allowed_purposes=frozenset(values),
                evidence_id=evidence_id,
            )

        if field == "certifications" and operator == "ANY_OF":
            values = condition.get("expected_strings")
            if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                raise ValueError("invalid approved certification condition")
            return CertificationRule(
                required_any_of=frozenset(values),
                evidence_id=evidence_id,
            )

        raise ValueError(f"unsupported approved condition: {field}/{operator}")
