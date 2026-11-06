'use strict';
// Unit navigation contains questions across source files; each score belongs to a question.
function questionEstimate(q){
 const a=q.classification.difficulty_assessment;
 if(q.source?.boundary_review)return null;
 if(q.classification.certainty!=='user_confirmed'&&a&&['unknown','pending_boundary'].includes(a.state))return null;
 return q.difficulty;
}
function questionDifficulty(q){
 const n=questionEstimate(q),a=q.classification.difficulty_assessment;
 if(n===null)return badge(q.source?.boundary_review?'분리 후 분류':'난이도 미분류','amber');
 return `<span class="question-difficulty" title="${esc((a?.basis||[q.classification.basis||'이전 문항별 지정 값']).join(' · '))}">${dots(n)}<small>${n<=4?'하':n<=7?'중':'상'} · ${a?.state==='user_confirmed'||q.classification.certainty==='user_confirmed'?'교사 지정':'추정'}</small></span>`;
}
function classificationPanel(q){
 const c=q.classification,a=c.difficulty_assessment;
 return `<div class="question-classification"><div class="row between"><h3>이 문항의 단원·난이도</h3>${btn('분류 수정','edit-classification','small',`data-id="${q.id}"`,'edit')}</div><p>${esc(c.course)} / ${esc(c.unit)} / ${esc(c.subunit||c.type)}</p><strong>${esc(c.type)}</strong><div class="row">${questionDifficulty(q)}</div><p class="note">${esc((a?.basis||[c.basis||'이전 문항별 분류 값']).join(' · '))}</p><small>${esc(a?.limitation||'해당 문항의 분류입니다. 시험지 전체의 등급을 부여하지 않습니다.')}</small></div>`;
}
function documentClassificationTable(qs){
 return `<details class="document-classifications"><summary>문항별 단원·난이도 보기 <span>${qs.length}개 항목</span></summary><div class="classification-table-scroll"><table class="table"><thead><tr><th>원본 번호</th><th>단원 / 세부단원</th><th>유형</th><th>문항 난이도</th><th></th></tr></thead><tbody>${qs.map(q=>`<tr><td>${esc(q.source.number??'묶음')}</td><td>${esc(q.classification.unit)}<small class="block">${esc(q.classification.subunit||q.classification.type)}</small></td><td>${esc(q.classification.type)}</td><td>${questionDifficulty(q)}</td><td>${btn('수정','edit-classification','small',`data-id="${q.id}"`,'edit')}</td></tr>`).join('')}</tbody></table></div><p class="note">문항별 추정입니다. 하 1~4 · 중 5~7 · 상 8~10. 분리 전 묶음과 판정 근거가 부족한 문항에는 난이도를 부여하지 않습니다.</p></details>`;
}
function unitScopeQuestions(){return data.questions.filter(q=>!filters.document||q.document_id===filters.document);}
function unitGroups(qs){
 const groups=new Map();
 for(const q of qs){
  const c=q.classification,course=c.course||'미상',unit=q.source?.boundary_review?'분리 대기':c.unit||'미분류',sub=q.source?.boundary_review?'문항 경계 확인':c.subunit||c.type||'미분류';
  const key=JSON.stringify([course,unit]);if(!groups.has(key))groups.set(key,{course,unit,count:0,subunits:new Map()});
  const g=groups.get(key);g.count++;g.subunits.set(sub,(g.subunits.get(sub)||0)+1);
 }
 return [...groups.values()].sort((a,b)=>a.course.localeCompare(b.course,'ko')||a.unit.localeCompare(b.unit,'ko'));
}
function unitQuestionMatches(q){
 const c=q.classification,score=questionEstimate(q),unit=q.source?.boundary_review?'분리 대기':c.unit;
 const search=[q.search_text,q.document_name,c.course,unit,c.subunit,c.type].join(' ').toLowerCase();
 return (!filters.search||search.includes(filters.search.toLowerCase()))&&(!filters.document||q.document_id===filters.document)&&(!filters.course||c.course===filters.course)&&(!filters.unit||unit===filters.unit)&&(!filters.subunit||(q.source?.boundary_review?'문항 경계 확인':c.subunit||c.type)===filters.subunit)&&(!filters.state||(filters.state==='available'?q.available:(q.answer?.verification||'untested')===filters.state))&&(!filters.difficulty||(filters.difficulty==='unknown'?score===null:score!==null&&score===Number(filters.difficulty)))&&(!filters.band||(filters.band==='unknown'?score===null:score!==null&&(filters.band==='low'?score<=4:filters.band==='medium'?score>=5&&score<=7:score>=8)));
}
function unitFilteredQuestions(){
 const qs=data.questions.filter(unitQuestionMatches);
 if(filters.sort==='difficulty-asc'||filters.sort==='difficulty-desc')qs.sort((a,b)=>{
  const x=questionEstimate(a),y=questionEstimate(b);if(x===null)return y===null?0:1;if(y===null)return -1;return filters.sort==='difficulty-desc'?y-x:x-y;
 });
 return qs;
}
function unitBrowser(){
 const qs=unitScopeQuestions(),groups=unitGroups(qs),courses=[...new Set(groups.map(g=>g.course))];
 return `<aside class="unit-browser"><div class="unit-browser-head"><strong>단원별 문항</strong><small>문항 수 · 검색 적용 전</small></div><button class="unit-tree-all ${!filters.unit&&!filters.course?'active':''}" data-action="unit-all">전체 문항 <b>${qs.length}</b></button>${courses.map(course=>`<section><h3>${esc(course)}</h3>${groups.filter(g=>g.course===course).map(g=>`<div class="unit-tree-group"><button class="unit-tree-parent ${filters.course===g.course&&filters.unit===g.unit&&!filters.subunit?'active':''}" data-action="unit-pick" data-course="${esc(g.course)}" data-unit="${esc(g.unit)}"><span>${esc(g.unit)}</span><b>${g.count}</b></button>${[...g.subunits].sort(([a],[b])=>a.localeCompare(b,'ko')).map(([sub,count])=>`<button class="unit-tree-child ${filters.course===g.course&&filters.unit===g.unit&&filters.subunit===sub?'active':''}" data-action="unit-pick" data-course="${esc(g.course)}" data-unit="${esc(g.unit)}" data-subunit="${esc(sub)}"><span>${esc(sub)}</span><b>${count}</b></button>`).join('')}</div>`).join('')}</section>`).join('')}</aside>`;
}
function unitQuestionsView(){
 const qs=unitFilteredQuestions(),doc=data.documents.find(d=>d.id===filters.document),parts=[filters.course,filters.unit,filters.subunit].filter(Boolean),job=data.jobs.find(j=>j.kind==='classify'&&['running','queued'].includes(j.state));
 return heading('단원별 문항','각 문제의 단원과 난이도로 찾아보세요. 여러 시험지의 문항도 같은 단원에 모입니다.',btn('문항 분류 다시 하기','classify-visible','','','restore')+btn('자료 가져오기','import','primary','','plus'))+(job?jobInline(job):'')+
 `<div class="unit-scope"><label>자료 범위 <select data-filter="document"><option value="">전체 자료의 문항</option>${data.documents.filter(d=>!d.trashed).map(d=>`<option value="${d.id}" ${filters.document===d.id?'selected':''}>${esc(d.name)}</option>`).join('')}</select></label><span>${doc?'이 자료 안의 문항을 단원별로 보고 있습니다.':'전체 자료의 문항을 단원별로 보고 있습니다.'}</span>${btn('조건 초기화','unit-reset','small','','restore')}</div>`+
 `<div class="unit-workspace">${unitBrowser()}<section class="unit-results"><div class="toolbar"><div class="searchbox">${icon('search')}<input id="search" placeholder="문항 본문·수식·유형 검색" value="${esc(filters.search)}"></div><select data-filter="band" aria-label="문항 난이도 구간"><option value="">모든 문항 난이도</option>${[['low','하 · 1~4'],['medium','중 · 5~7'],['high','상 · 8~10'],['unknown','난이도 미분류']].map(([v,t])=>`<option value="${v}" ${filters.band===v?'selected':''}>${t}</option>`).join('')}</select><select data-filter="difficulty" aria-label="개별 난이도"><option value="">세부 점수</option>${Array.from({length:10},(_,i)=>`<option value="${i+1}" ${Number(filters.difficulty)===i+1?'selected':''}>${i+1}/10</option>`).join('')}</select><select data-filter="state" aria-label="검증 상태"><option value="">모든 검증 상태</option>${[['available','자동 사용 가능'],['untested','미검증'],['held','보류'],['failed','충돌 / 실패']].map(([v,t])=>`<option value="${v}" ${filters.state===v?'selected':''}>${t}</option>`).join('')}</select><select data-filter="sort" aria-label="문항 정렬"><option value="">저장 순서</option><option value="difficulty-asc" ${filters.sort==='difficulty-asc'?'selected':''}>쉬운 문항부터</option><option value="difficulty-desc" ${filters.sort==='difficulty-desc'?'selected':''}>어려운 문항부터</option></select></div>`+
 `<div class="section-heading"><div><h2>${esc(parts.join(' / ')||'전체 단원')}</h2><div class="result-count"><strong>${qs.length}</strong>문항 · 개별 문항의 분류·난이도</div></div><button class="link" data-action="select-visible">${qs.length&&qs.every(q=>selected.has(q.id))?'선택 해제':'결과 전체 선택'}</button></div>`+
 (qs.length?`<div class="q-grid">${qs.map(qCard).join('')}</div>`:`<div class="card">${empty('조건에 맞는 문항이 없습니다','단원이나 난이도 조건을 바꾸세요. 분리 전 묶음은 분리 대기에서 확인할 수 있습니다.')}<div class="empty-reset">${btn('조건 초기화','unit-reset','primary','','restore')}</div></div>`)+`</section></div>`;
}
function editClassification(q){
 const c=q.classification,score=questionEstimate(q);
 if(q.source?.boundary_review){toast('먼저 문항 경계를 확정해 주세요.',true);return;}
 const a=c.difficulty_assessment;
 modal('이 문항의 분류·난이도 수정',`<p class="note">${esc(q.document_name||'생성 문항')} · 원본 ${esc(q.source.number||'')}번. 다른 문항의 난이도는 바뀌지 않습니다. 정답·해설과 기존 시험 기록은 유지됩니다.</p><form id="classificationForm" data-id="${q.id}" data-revision="${q.revision}"><div class="form-grid">${[['course','과목',c.course],['unit','단원',c.unit],['subunit','세부단원',c.subunit||c.type],['type','유형',c.type]].map(([key,label,value])=>`<div class="field"><label>${label}<input name="${key}" maxlength="100" value="${esc(value)}" required></label></div>`).join('')}<div class="field"><label>이 문항의 난이도<select name="difficulty" required><option value="">선택해 주세요</option>${Array.from({length:10},(_,i)=>`<option value="${i+1}" ${score===i+1?'selected':''}>${i+1} / 10 · ${i<4?'하':i<7?'중':'상'}</option>`).join('')}</select></label></div></div><div class="field"><label>문항 분류·난이도 근거<textarea name="reason" maxlength="1000" required>${esc((a?.basis||[c.basis||'교사가 해당 문항의 내용과 풀이를 확인했습니다.']).join(' · '))}</textarea></label></div></form>`,btn('이 문항만 저장','save-classification','primary','','save'));
}
window.unitAction=async(action,el)=>{
 if(action==='unit-pick'){filters.course=el.dataset.course;filters.unit=el.dataset.unit;filters.subunit=el.dataset.subunit||'';renderPage();return true;}
 if(action==='unit-all'){filters.course='';filters.unit='';filters.subunit='';renderPage();return true;}
 if(action==='unit-reset'){filters={search:'',unit:'',state:'',difficulty:''};renderPage();return true;}
 if(action==='work-units'){filters={search:'',unit:'',state:'',difficulty:'',document:workDocument};navigate('questions');return true;}
 if(action==='edit-classification'){editClassification(data.questions.find(q=>q.id===el.dataset.id));return true;}
 if(action==='save-classification'){
  const form=$('#classificationForm');if(!form.reportValidity())return true;
  const values=Object.fromEntries(new FormData(form));values.difficulty=Number(values.difficulty);
  await api('edit_classification',{id:form.dataset.id,revision:Number(form.dataset.revision),values});closeModal();await refresh();if(drawerId)showDetail(drawerId,drawerTab);toast('이 문항의 분류와 난이도를 저장했습니다.');return true;
 }
 if(action==='classify-visible'){
  const ids=unitFilteredQuestions().filter(q=>q.classification.certainty!=='user_confirmed').map(q=>q.id);
  if(!ids.length){toast('현재 결과에는 자동으로 다시 분류할 문항이 없습니다. 교사 지정 값은 문항별 수정으로 바꿀 수 있습니다.');return true;}
  modal('개별 문항 분류 다시 하기',`<p>현재 검색 결과 중 ${ids.length}문항을 하나씩 읽어 단원·세부단원·유형·난이도를 다시 제안합니다.</p><p class="note">교사가 직접 지정한 값은 유지합니다. 경계 미확정 묶음은 분류 대기로 남깁니다. 정답·해설과 과거 시험은 보존합니다.</p>`,btn('문항별 자동 분류 시작','classify-go','primary',`data-ids="${ids.join(',')}"`,'restore'));return true;
 }
 if(action==='classify-go'){await api('classify',{ids:el.dataset.ids.split(',')});closeModal();await refresh();toast('문항별 단원·난이도를 다시 분류합니다.');return true;}
 return false;
};
