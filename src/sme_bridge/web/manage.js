"use strict";
// A process-local token protects only loopback tools; it is NOT an upstream API key.
(() => {
  const el = id => document.getElementById(id);
  const make = (tag, text) => { const n = document.createElement(tag); n.textContent = text; return n; };
  const fields = {hq_region: "본사 지역", employee_count: "종업원 수", business_age_years: "만 업력", query_date: "신청기간", industry_code: "업종", annual_sales_band: "매출 구간", funding_purpose: "자금 목적", certifications: "인증"};
  let token, activeNotice, source, pages = [], rules = [], sequence = 0, pollTimer;
  let enabled = false, ocrEnabled = false, lastActiveJob = null;
  const status = text => { el("review-status").textContent = text; };
  const location = p => p.location_kind === "SECTION" ? `HWPX 섹션 ${p.page_number} (실제 페이지 아님)` : `PDF ${p.page_number}페이지`;
  const canOCR = () => ocrEnabled && pages.some(p => p.document_kind === "PDF");
  function refreshOCRStatus() {
    el("ocr-button").disabled = !canOCR();
    el("ocr-status").textContent = !ocrEnabled ? "OCR 준비: python scripts/setup_ocr.py 실행 후 화면을 새로고침하세요." : pages.some(p => p.document_kind === "HWPX") ? "HWPX는 본문 추출만 지원합니다. OCR 미리보기는 저장된 PDF 전용입니다." : "한국어·영어 OCR 모델 준비 완료. 저장된 PDF를 선택하세요. 결과는 참고용이며 자동 승인하지 않습니다.";
  }
  async function request(path, body) {
    const response = await fetch(`/v1/manage${path}`, {
      headers: {"X-Bridge-Token": token || "", "Content-Type": "application/json"},
      ...(body === undefined ? {} : {method: "POST", body: JSON.stringify(body)})
    });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : `입력값 또는 인용문을 확인하세요 (${response.status}).`);
    return result;
  }
  async function jobs() {
    if (!enabled) return;
    clearTimeout(pollTimer);
    try {
      const list = await request("/jobs");
      const running = list.find(j => ["QUEUED", "RUNNING"].includes(j.status));
      el("collect-button").disabled = !!running;
      el("retry-document").disabled = !!running;
      el("collection-jobs").replaceChildren();
      for (const j of list.slice(0, 5)) {
        const detail = make("details", "");
        detail.append(make("summary", `${j.status} · ${j.processed}/${j.total}건 · ${new Date(j.started_at).toLocaleString("ko-KR")}`));
        if (j.error_code) detail.append(make("p", j.error_code));
        for (const item of j.items) detail.append(make("p", `${item.notice_id}: ${item.status}`));
        el("collection-jobs").append(detail);
      }
      if (lastActiveJob && !running) {
        lastActiveJob = null;
        await loadNotices();
        if (activeNotice) await showNotice(activeNotice.notice_id);
      }
      if (running) { lastActiveJob = running.job_id; pollTimer = setTimeout(jobs, 2000); }
    } catch (error) { el("collection-jobs").textContent = error.message; }
  }
  async function collect(body) {
    el("collect-button").disabled = el("retry-document").disabled = true;
    try { const j = await request("/jobs", body); lastActiveJob = j.job_id; await jobs(); }
    catch (error) { el("collection-jobs").textContent = error.message; el("collect-button").disabled = el("retry-document").disabled = false; }
  }
  function renderRules() {
    el("review-rules").replaceChildren();
    el("review-confirmed").checked = false;
    el("scope-complete").checked = false;
    for (const [index, item] of rules.entries()) {
      const card = make("article", ""); card.className = "passage";
      card.append(make("h3", `검토 조건 ${index + 1}: ${fields[item.rule.field] || item.rule.field}`), make("pre", JSON.stringify(item.rule, null, 2)), make("p", item.citation.passage));
      const button = make("button", "이 조건 삭제"); button.type = "button";
      button.addEventListener("click", () => { rules.splice(index, 1); renderRules(); });
      card.append(button); el("review-rules").append(card);
    }
    el("export-review").disabled = !rules.length;
  }
  function original() {
    const page = pages.find(p => p.page_number === Number(el("rule-page").value));
    el("review-original").textContent = page ? page.text : "선택할 저장 원문이 없습니다.";
    el("rule-quote").value = "";
  }
  function toggleField() {
    const field = el("rule-field").value;
    for (const id of ["values", "min", "max", "start", "end"]) {
      el(`rule-${id}-label`).hidden = id === "values" ? ["employee_count", "business_age_years", "query_date"].includes(field) : ["min", "max"].includes(id) ? !["employee_count", "business_age_years"].includes(field) : field !== "query_date";
    }
    el("rule-values").placeholder = field === "annual_sales_band" ? "UNDER_1B_KRW, FROM_1B_TO_5B_KRW, OVER_5B_KRW" : field === "funding_purpose" ? "WORKING_CAPITAL, FACILITY_CAPITAL, BOTH" : "예: 대전, 서울 / J62 / 인증명";
  }
  async function selectNotice(notice) {
    activeNotice = notice;
    const thisSequence = ++sequence;
    el("review-panel").hidden = !enabled;
    source = null; pages = []; rules = [];
    renderRules(); el("suggestions").replaceChildren(); el("rule-page").replaceChildren();
    el("review-original").textContent = ""; el("ocr-output").textContent = "";
    el("rule-quote").value = ""; el("add-rule").disabled = true;
    refreshOCRStatus();
    if (!enabled) return;
    status("현재 원문과 초안 불러오는 중…");
    try {
      const result = await request(`/notices/${encodeURIComponent(notice.notice_id)}/suggestions`);
      const found = [];
      for (let offset = 0; offset < 5000; offset += 100) {
        const query = new URLSearchParams({version: notice.version_hash, limit: 100, offset});
        const response = await fetch(`/v1/notices/${encodeURIComponent(notice.notice_id)}/passages?${query}`);
        if (!response.ok) throw new Error("원문을 불러오지 못했습니다.");
        const batch = (await response.json()).items;
        found.push(...batch.filter(p => p.pdf_sha256 === result.document_hash));
        if (batch.length < 100) break;
      }
      if (thisSequence !== sequence) return;
      if (result.version_hash !== notice.version_hash) throw new Error("공고 버전이 변경되었습니다. 상세를 다시 여세요.");
      source = result; pages = found;
      refreshOCRStatus();
      status(result.warnings.join(" "));
      for (const page of pages) {
        const option = make("option", location(page) + (page.requires_ocr || page.security_flags.length ? " · 승인 근거 사용 불가" : ""));
        option.value = page.page_number; option.disabled = page.requires_ocr || !!page.security_flags.length;
        el("rule-page").append(option);
      }
      const usable = pages.find(p => !p.requires_ocr && !p.security_flags.length);
      if (usable) el("rule-page").value = usable.page_number;
      el("add-rule").disabled = !usable;
      original();
      for (const suggestion of result.suggestions) {
        const card = make("article", ""); card.className = "passage";
        card.append(make("h3", `미검토 초안 · ${fields[suggestion.rule.field] || suggestion.rule.field}`), make("p", `${location({page_number: suggestion.citation.page_number, location_kind: suggestion.location_kind})}: ${suggestion.citation.passage}`), make("pre", JSON.stringify(suggestion.rule, null, 2)));
        const button = make("button", "입력 양식으로 가져오기"); button.type = "button";
        button.addEventListener("click", () => {
          const r = suggestion.rule;
          el("rule-field").value = r.field; toggleField();
          el("rule-page").value = suggestion.citation.page_number; original();
          el("rule-quote").value = suggestion.citation.passage;
          el("rule-values").value = (r.allowed_regions || r.allowed_codes || r.required_any_of || []).join(", ");
          el("rule-min").value = r.minimum ?? ""; el("rule-max").value = r.maximum ?? "";
          el("rule-start").value = r.starts_on || ""; el("rule-end").value = r.ends_on || "";
          el("rule-form").scrollIntoView({block: "center", behavior: "smooth"});
        });
        card.append(button); el("suggestions").append(card);
      }
    } catch (error) { if (thisSequence === sequence) status(error.message); }
  }
  el("collection-form").addEventListener("submit", e => { e.preventDefault(); collect({count: Number(el("collection-count").value), documents: el("collect-documents").checked}); });
  el("retry-document").addEventListener("click", () => { if (activeNotice) collect({notice_id: activeNotice.notice_id, documents: true}); });
  el("rule-field").addEventListener("change", toggleField);
  el("rule-page").addEventListener("change", original);
  el("rule-form").addEventListener("submit", e => {
    e.preventDefault();
    try {
      if (!source || rules.length >= 100) throw new Error("원문을 선택하거나 조건 수를 확인하세요.");
      const page = pages.find(p => p.page_number === Number(el("rule-page").value));
      const quote = el("rule-quote").value;
      if (!page || page.requires_ocr || page.security_flags.length || !page.text.includes(quote)) throw new Error("안전한 원문에서 정확한 인용문을 복사해주세요.");
      const evidence_id = `${source.notice_id}:${source.version_hash}:review-${crypto.randomUUID().replace(/-/g, "").slice(0, 16)}`;
      const field = el("rule-field").value, rule = {field, evidence_id};
      if (["employee_count", "business_age_years"].includes(field)) {
        rule.minimum = el("rule-min").value === "" ? null : Number(el("rule-min").value);
        rule.maximum = el("rule-max").value === "" ? null : Number(el("rule-max").value);
        if (rule.minimum === null && rule.maximum === null || rule.minimum !== null && rule.maximum !== null && rule.minimum > rule.maximum) throw new Error("최소·최대 포함값 범위를 확인하세요.");
      } else if (field === "query_date") {
        rule.starts_on = el("rule-start").value; rule.ends_on = el("rule-end").value;
        if (!rule.starts_on || !rule.ends_on || rule.starts_on > rule.ends_on) throw new Error("신청기간을 확인하세요.");
      } else {
        const key = {hq_region: "allowed_regions", industry_code: "allowed_codes", annual_sales_band: "allowed_bands", funding_purpose: "allowed_purposes", certifications: "required_any_of"}[field];
        rule[key] = el("rule-values").value.split(",").map(s => s.trim()).filter(Boolean);
        if (!rule[key].length) throw new Error("조건의 허용값을 입력하세요.");
      }
      rules.push({rule, citation: {evidence_id, pdf_sha256: page.pdf_sha256, page_number: page.page_number, passage: quote}});
      renderRules(); status("검토 목록에 추가했습니다. 다운로드 전에 원문 대조 여부를 확인하세요.");
    } catch (error) { status(error.message); }
  });
  el("export-review-form").addEventListener("submit", async e => {
    e.preventDefault();
    if (!source || !rules.length) return;
    const currentSequence = sequence;
    el("export-review").disabled = true;
    try {
      const draft = await request("/review/validate", {notice_id: source.notice_id, version_hash: source.version_hash, approved_by: el("reviewer").value.trim(), scope_complete: el("scope-complete").checked, conditions: rules.map(r => r.rule), citations: rules.map(r => r.citation)});
      if (currentSequence !== sequence) return;
      const url = URL.createObjectURL(new Blob([JSON.stringify(draft, null, 2)], {type: "application/json"}));
      const anchor = make("a", ""); anchor.href = url; anchor.download = `review-${draft.notice_id.replace(/[^a-zA-Z0-9_-]/g, "_")}.json`;
      document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      status("원문 검증을 통과해 파일을 내려받았습니다. 아직 승인 등록되지 않았습니다. docs/review-guide.md의 등록 명령을 사용하세요.");
    } catch (error) { if (currentSequence === sequence) status(error.message); }
    finally { el("export-review").disabled = !rules.length; }
  });
  el("ocr-form").addEventListener("submit", async e => {
    e.preventDefault(); if (!activeNotice || !canOCR()) return;
    const currentSequence = sequence;
    const numbers = el("ocr-pages").value.split(",").map(s => Number(s.trim()));
    if (numbers.length > 3 || numbers.some(n => !Number.isInteger(n) || n < 1) || new Set(numbers).size !== numbers.length) { el("ocr-output").textContent = "서로 다른 페이지 번호를 1~3개 입력하세요."; return; }
    el("ocr-button").disabled = true; el("ocr-output").textContent = "OCR 실행 중… (최대 60초)";
    try {
      const result = await request(`/notices/${encodeURIComponent(activeNotice.notice_id)}/ocr`, {pages: numbers});
      if (currentSequence === sequence) el("ocr-output").textContent = result.warning + "\n" + result.pages.map(p => `\n${p.page_number}페이지\n${p.text}\n${p.security_flags.join(", ")}`).join("\n");
    } catch (error) { if (currentSequence === sequence) el("ocr-output").textContent = error.message; }
    finally { refreshOCRStatus(); }
  });
  document.addEventListener("bridge-notice", e => selectNotice(e.detail));
  (async () => {
    try {
      const info = await request("/status"); token = info.token; enabled = info.enabled; ocrEnabled = info.ocr_available;
      el("management-controls").hidden = !enabled;
      el("management-status").textContent = enabled ? "이 컴퓨터에서만 사용할 수 있는 관리 기능입니다. 서버 재시작 시 진행 중 수집은 중단 상태로 기록됩니다." : "관리 기능이 비활성화되어 있습니다. python scripts/run_local.py로 로컬 서버를 실행하세요.";
      refreshOCRStatus();
      if (activeNotice) await selectNotice(activeNotice);
      await jobs();
    } catch (error) { el("management-status").textContent = "로컬 관리 기능을 사용할 수 없습니다: " + error.message; }
  })();
})();
