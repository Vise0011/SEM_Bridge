"use strict";
const $ = id => document.getElementById(id);
let offset = 0, selected = null, passageOffset = 0;
const labels = {PASS:"조건 충족",FAIL:"조건 불충족",UNKNOWN:"확인 필요"};
const fieldLabels = {hq_region:"본사 지역",employee_count:"종업원 수",business_age_years:"업력",query_date:"신청기간",industry_code:"업종",annual_sales_band:"연 매출",funding_purpose:"자금 목적",certifications:"인증"};
const node = (tag,text,cls) => {const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
function notify(text,error=false){$("message").textContent=text;$("message").className=text?"alert"+(error?" error":""):"";}
async function api(url,options){const r=await fetch(url,options);const data=await r.json();if(!r.ok)throw new Error(r.status===422?"입력값을 확인하세요. 날짜·업종 코드·인원 범위를 확인해주세요.":typeof data.detail==="string"?data.detail:`요청 실패 (${r.status})`);return data;}
function link(url,label){try{const u=new URL(url);if(u.protocol!=="https:"||!["www.bizinfo.go.kr","bizinfo.go.kr"].includes(u.hostname))return node("span","공식 링크를 확인해주세요.");const a=node("a",label);a.href=u.href;a.target="_blank";a.rel="noopener noreferrer";return a;}catch{return node("span","");}}
async function loadNotices(){notify("");$("notices").replaceChildren();$("list-status").textContent="불러오는 중…";try{const query=new URLSearchParams({q:$("search").value,limit:10,offset});const data=await api(`/v1/notices?${query}`);for(const {snapshot:s,fetched_at} of data.items){const card=node("article",undefined,"card");card.append(node("h3",s.title),node("p",`${s.authority} · ${s.application_period_raw||"신청기간 확인 필요"}`,"muted"));const b=node("button","상세 및 근거 보기");b.type="button";b.addEventListener("click",()=>showNotice(s.notice_id));card.append(b,link(s.url,"공식 공고 ↗"));$("notices").append(card);}$("list-status").textContent=data.items.length?`${data.items.length}건 표시 · 수집 시각 ${new Date(data.items[0].fetched_at).toLocaleString("ko-KR")}`:"공고가 없습니다. 공고를 수집하거나 검색어를 바꿔주세요.";$("page-label").textContent=`${offset/10+1}페이지`;$("previous").disabled=offset===0;$("next").disabled=data.items.length<10;}catch(e){notify(e.message,true);$("list-status").textContent="목록을 불러오지 못했습니다.";}}
let detailSequence=0;
async function showNotice(id){const sequence=++detailSequence;try{const r=await api(`/v1/notices/${encodeURIComponent(id)}`);if(sequence!==detailSequence)return;selected=r.snapshot;passageOffset=0;$("detail-section").hidden=false;$("detail").replaceChildren(node("h3",selected.title),node("p",selected.summary.replace(/<[^>]*>/g," ")),node("p",`신청기간: ${selected.application_period_raw||"기관 확인 필요"}`),node("p",`공고 버전: ${selected.version_hash}`,"muted"),link(selected.url,"공식 원문 보기 ↗"));$("passage-search").value="";document.dispatchEvent(new CustomEvent("bridge-notice",{detail:selected}));await loadPassages(false);if(sequence===detailSequence)$("detail-section").scrollIntoView({behavior:"smooth",block:"start"});}catch(e){notify(e.message,true);}}
let passageSequence=0;
async function loadPassages(append){if(!selected)return;const sequence=++passageSequence,current=selected;try{const query=new URLSearchParams({q:$("passage-search").value,version:current.version_hash,limit:10,offset:passageOffset});const r=await api(`/v1/notices/${encodeURIComponent(current.notice_id)}/passages?${query}`);if(sequence!==passageSequence||current!==selected)return;if(!append)$("passages").replaceChildren();for(const p of r.items){const card=node("article",undefined,"passage");card.append(node("h3",p.location_kind==="SECTION"?`HWPX 섹션 ${p.page_number} (실제 페이지 아님)`:`${p.page_number}페이지`),node("p",`문서 해시: ${p.pdf_sha256}`,"muted"));if(p.requires_ocr)card.append(node("p","문자 인식 또는 원문 변환 검토가 필요합니다.","alert"));if(p.security_flags.length)card.append(node("p","의심 문구가 포함되어 추가 검토가 필요합니다.","alert"));card.append(node("pre",p.text||"추출된 텍스트가 없습니다."));$("passages").append(card);}$("passage-status").textContent=r.items.length?"저장된 첨부에서 추출한 원문입니다. 문서 해시와 위치를 확인하세요.":"일치하는 저장 원문이 없습니다. 첨부 수집 상태 또는 검색어를 확인하세요.";$("more-passages").hidden=r.items.length<10;}catch(e){notify(e.message,true);}}
function renderCase(data) {
  $("results").replaceChildren();
  $("case-id").value=data.case_id;
  $("results").append(node("p",`결과 번호: ${data.case_id}`,"muted"),node("p",data.source==="demo"?"합성 공고 데모 결과":"공식 공고 사전진단 결과"));
  for(const note of data.notes) $("results").append(node("p",note,"alert"));
  for(const p of data.programs) {
    const card=node("article",undefined,"result");
    card.append(node("h3",p.title||p.program_id),node("span",labels[p.status],`badge ${p.status}`));
    if(p.source_kind==="SYNTHETIC_DEMO") card.append(node("p","합성 데모 공고","muted"));
    for(const reason of p.review_reasons) card.append(node("p",reason,"alert"));
    const list=node("ul");
    for(const rule of p.rule_results) {
      const li=node("li",`${fieldLabels[rule.field]||rule.field}: ${labels[rule.status]} · 관측값 ${JSON.stringify(rule.observed)}`);
      const evidence=p.evidence.find(e=>e.evidence_id===rule.evidence_id);
      if(evidence) {
        const position = evidence.page ? evidence.location_kind === "SECTION" ? ` (HWPX 섹션 ${evidence.page}, 실제 페이지 아님)` : ` (${evidence.page}페이지)` : "";
        li.append(node("p",`근거${position}: ${evidence.passage}`));
        if(evidence.source_url) li.append(link(evidence.source_url,"근거 원문 ↗"));
      }
      list.append(li);
    }
    card.append(list);
    for(const q of p.follow_up_questions) card.append(node("p",q));
    if(p.missing_evidence_ids.length) card.append(node("p","일부 근거를 확인하지 못했습니다.","alert"));
    if(p.source_url) card.append(link(p.source_url,"공식 공고 ↗"));
    $("results").append(card);
  }
}
$("search-form").addEventListener("submit",e=>{e.preventDefault();offset=0;loadNotices();});
$("previous").addEventListener("click",()=>{offset=Math.max(0,offset-10);loadNotices();});
$("next").addEventListener("click",()=>{offset+=10;loadNotices();});
$("passage-form").addEventListener("submit",e=>{e.preventDefault();passageOffset=0;loadPassages(false);});
$("more-passages").addEventListener("click",()=>{passageOffset+=10;loadPassages(true);});
$("profile-form").addEventListener("submit",async e=>{e.preventDefault();notify("");const source=$("source").value;const params=new URLSearchParams({source});if($("selected-only").checked){if(!selected||source!=="official"){notify("공식 공고를 선택하고 진단 대상을 공식 공고로 설정하세요.",true);return;}params.set("notice_id",selected.notice_id);}const profile={business_type:$("business-type").value,query_date:$("query-date").value};for(const [id,key] of [["region","hq_region"],["established","established_date"],["industry","industry_code"],["sales","annual_sales_band"],["funding","funding_purpose"]])if($(id).value.trim())profile[key]=$(id).value.trim();if($("employees").value!=="")profile.employee_count=Number($("employees").value);profile.certifications=$("certifications").value.split(",").map(s=>s.trim()).filter(Boolean);$("evaluate").disabled=true;try{renderCase(await api(`/v1/cases?${params}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(profile)}));}catch(err){notify(err.message,true);}finally{$("evaluate").disabled=false;}});
$("case-form").addEventListener("submit",async e=>{e.preventDefault();try{renderCase(await api(`/v1/cases/${encodeURIComponent($("case-id").value)}`));$("results").scrollIntoView({behavior:"smooth"});}catch(err){notify(err.message,true);}});
const today=new Date();$("query-date").value=`${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,"0")}-${String(today.getDate()).padStart(2,"0")}`;
loadNotices();
