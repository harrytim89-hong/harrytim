'use strict';
const matchLabels={exact:'동일 문항',template:'수치 변형 후보',related:'유사 문항'};
let similarRequest=0;

function bankOverview(){
 const qs=data.questions.filter(q=>!q.source.boundary_review),ready=qs.filter(q=>q.available).length;
 return `<section class="bank-overview" aria-label="자료실 현황">${[[qs.length,'전체 문항','questions'],[ready,'출제 가능한 문항','shield'],[data.exams.length,'시험 · 과제','exams'],[data.students.length,'등록 학생','students']].map(([n,label,ic])=>`<div class="bank-metric"><span class="metric-icon">${icon(ic)}</span><div><span>${label}</span><strong>${n.toLocaleString()}<small>${ic==='students'?'명':'개'}</small></strong></div></div>`).join('')}</section><div class="bank-flow"><div><span class="flow-dot"></span><strong>수업 준비, 하나의 흐름으로.</strong><span>문항을 모으고, 연결하고, 학생의 성장을 확인하세요.</span></div><div class="flow-links"><button data-action="import">01 가져오기</button><i>→</i><button data-nav="questions">02 문항 선택</button><i>→</i><button data-nav="exams">03 시험 제작</button><i>→</i><button data-nav="reports">04 성적표</button></div></div>`;
}

function schoolTabs(){
 return `<div class="school-tabs" role="group" aria-label="학교 범위">${[['','전체 범위'],['중등','중등'],['고등','고등'],['중·고 공통','중·고 공통'],['미분류','미분류']].map(([v,t])=>`<button class="${(filters.school||'')===v?'active':''}" data-action="school-filter" data-level="${v}" aria-pressed="${(filters.school||'')===v}">${t}</button>`).join('')}<span>중·고 공통 문항은 중등·고등에 함께 표시됩니다.</span></div>`;
}

function schoolMatches(q){return !filters.school||q.school_level===filters.school||(['중등','고등'].includes(filters.school)&&q.school_level==='중·고 공통');}

async function loadSimilar(id,full=false){
 const request=++similarRequest,target=$('#similarResults');if(!target)return;
 target.innerHTML='<div class="similar-loading">문항의 본문과 수식 구조를 비교하고 있습니다…</div>';
 try{
  const result=await api('similar_questions',{id,limit:full?30:3});
  if(request!==similarRequest||drawerId!==id||!target.isConnected)return;
  const matches=result.matches.filter(m=>data.questions.some(q=>q.id===m.id&&q.revision===m.revision));
  target.innerHTML=`<div class="similar-summary"><strong>${result.total.toLocaleString()}개의 연관 문항</strong>${badge('동일 '+result.exact_count+'개','green')}</div>`+(matches.length?matches.map(m=>{
   const q=data.questions.find(q=>q.id===m.id);
   return `<article class="similar-item"><div class="row between">${badge(matchLabels[m.kind],m.kind==='exact'?'green':'purple')}<span class="match-score">검색 점수 <b>${m.score}</b><small> / 100</small></span></div><h3>${esc(q.classification.unit)} <span>· ${esc(q.source.number||'생성')}번</span></h3><div class="similar-excerpt q-body">${blocks(q.body.blocks.slice(0,2))}</div><p class="similar-reasons">${esc(m.reasons.join(' · '))}</p><div class="row between"><small class="muted">${esc(q.document_name||'생성 문항')}</small><div class="row">${btn('비교','compare-questions','small',`data-id="${q.id}" data-source="${id}"`,'search')}${btn(composer.some(i=>i.id===q.id)?'담김':'시험에 담기','question-add','small',`data-id="${q.id}"`,'plus')}</div></div></article>`;
  }).join(''):'<div class="similar-empty">현재 자료실에 비교 기준을 충족하는 문항이 없습니다.<br>다른 자료를 가져오면 함께 검색됩니다.</div>')+`<p class="note">${esc(result.method)}</p>`+(full&&result.total>30?'<p class="note">관련도가 높은 30개를 표시합니다.</p>':'');
 }catch(e){if(request===similarRequest&&target.isConnected)target.innerHTML=`<div class="hold-block">${esc(e.message)}</div>`;}
}

function reportExtras(r){
 return `<section class="report-followup"><div><h3>보완할 유형</h3>${Object.entries(r.weak_types||{}).map(([label,positions])=>`<div class="weak-type"><strong>${esc(label)}</strong><span>${positions.join(', ')}번 · 오답 / 부분정답 / 무응답</span></div>`).join('')||`<p class="note">${r.attempt.state==='absent'?'미응시 기록입니다.':r.pending?'채점을 완료하면 보완할 유형을 확인할 수 있습니다.':'이번 시험에서 보완할 오답이 없습니다.'}</p>`}</div><div><div class="row between"><h3>교사 코멘트</h3><span class="muted">저장한 내용은 PDF에 반영됩니다</span></div><textarea id="reportComment" aria-label="교사 코멘트" maxlength="4000" placeholder="잘한 점과 다음 학습 방향을 적어 주세요.">${esc(r.comment||'')}</textarea><div class="row between"><span id="commentStatus" class="muted" aria-live="polite"></span>${btn('코멘트 저장','save-report-comment','small',`data-id="${r.attempt.id}"`,'save')}</div></div></section>`;
}

window.assistantAction=async(action,el)=>{
 if(action==='bank-page'){filters.page=Number(el.dataset.page);renderPage();$('.unit-results')?.scrollIntoView({block:'start'});return true;}
 if(action==='school-filter'){filters.page=1;filters.school=el.dataset.level;filters.course='';filters.unit='';filters.subunit='';renderPage();return true;}
 if(action==='similar-questions'){showDetail(el.dataset.id,'similar');return true;}
 if(action==='compare-questions'){
  const source=data.questions.find(q=>q.id===el.dataset.source),candidate=data.questions.find(q=>q.id===el.dataset.id);
  if(!source||!candidate)throw Error('문항이 변경되었습니다. 검색을 다시 실행하세요.');
  modal('문항 나란히 비교',`<div class="question-compare">${[[source,'기준 문항'],[candidate,'검색된 문항']].map(([q,label])=>`<section><div class="row between"><h3>${label}</h3>${questionDifficulty(q)}</div><p class="muted">${esc(q.classification.unit)} · ${esc(q.source.number||'생성')}번</p>${body(q)}<p class="note">${esc(q.document_name||'생성 문항')} · ${esc(q.classification.type)}</p>${stateBadge(q)}</section>`).join('')}</div>`,(composer.some(i=>i.id===source.id)?btn('시험의 기준 문항 교체','replace-similar','',`data-source="${source.id}" data-id="${candidate.id}"`,'restore'):'')+btn('검색 문항 담기','question-add','primary',`data-id="${candidate.id}"`,'plus'),true);
  return true;
 }
 if(action==='replace-similar'){
  const index=composer.findIndex(i=>i.id===el.dataset.source),q=data.questions.find(q=>q.id===el.dataset.id);
  if(index<0||!q)throw Error('시험 구성에서 기준 문항을 찾을 수 없습니다.');
  if(composer.some(i=>i.id===q.id))throw Error('이미 시험에 담긴 문항입니다.');
  composer[index]={...composer[index],id:q.id};closeModal();closeDrawer();navigate('exams');toast('순서와 배점을 유지하며 문항을 교체했습니다.');return true;
 }
 if(action==='save-report-comment'){
  el.disabled=true;
  try{const result=await api('report_comment',{id:el.dataset.id,comment:$('#reportComment').value});if(reportId===el.dataset.id){reportData=result;$('#commentStatus').textContent='저장 완료';}toast('교사 코멘트를 저장했습니다.');}finally{el.disabled=false;}return true;
 }
 return false;
};

document.addEventListener('keydown',e=>{
 if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'&&!e.target.matches('textarea,input')){e.preventDefault();navigate('questions');$('#search')?.focus();}
});
document.addEventListener('input',e=>{if(e.target.id==='reportComment')$('#commentStatus').textContent='저장하지 않은 변경 사항';});
