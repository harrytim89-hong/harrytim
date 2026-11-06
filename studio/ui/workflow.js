'use strict';
// A document remains the user's context from import through exam composition.
let workDocument=null,workSummary=null,workQuestion=null,workTab='question',followJob=null;
let sourceCache=new Map(),workBusy=false,lastCreatedExam=null;
window.noteCreatedExam=(id)=>{lastCreatedExam=id;};
window.examWorkflowGuidance=()=>lastCreatedExam?`<div class="work-next"><div><strong>시험을 저장했습니다. 다음은 출력 또는 학생 배정입니다.</strong><p>① 출력에서 문제지·정답·해설 저장 → ② 학생 배정 → ③ 성적표에서 답안 입력·채점</p></div><div class="row">${btn('출력','export-dialog','primary',`data-id="${lastCreatedExam}"`,'download')}${btn('학생 배정','assign-dialog','',`data-id="${lastCreatedExam}"`,'students')}</div></div>`:'';
const workLabels={import:'자료 가져오기',reparse:'문항 자동 재분리',classify:'문항별 단원·난이도 분류',proofread:'원문·문장 검수',explain:'정답·해설 생성',variant:'변형 생성'};

window.followImportJob=(id)=>{followJob=id;workDocument=null;workSummary=null;page='library';closeDrawer();renderPage();};
window.workflowDataUpdated=async()=>{
 if(followJob){
  const job=data.jobs.find(j=>j.id===followJob);
  if(job?.document_ids?.length){workDocument=job.document_ids[0];workQuestion=null;followJob=null;page='library';}
 }
 if(!workDocument)return;
 const requestedDocument=workDocument;
 try{
  const loaded=await api('document_review',{id:requestedDocument});
  if(workDocument!==requestedDocument)return;
  workSummary=loaded;
  const qs=documentQuestions();if(!qs.some(q=>q.id===workQuestion))workQuestion=qs[0]?.id||null;
  const q=selectedWorkQuestion();
  if(q){const key=q.id+':'+q.revision;if(!sourceCache.has(key)){
   try{sourceCache.set(key,await api('source_view',{id:q.id}));}catch(e){sourceCache.set(key,{blocks:[],message:e.message,error:true});}
   if(sourceCache.size>40)sourceCache.delete(sourceCache.keys().next().value);
  }}
 }catch(e){if(workDocument===requestedDocument){workSummary=null;workDocument=null;toast(e.message,true);}}
};
window.openDocumentWorkflow=async(id)=>{workDocument=id;workQuestion=null;workTab='question';await window.workflowDataUpdated();navigate('library');};
function documentQuestions(){return data.questions.filter(q=>q.document_id===workDocument);}
function selectedWorkQuestion(){return data.questions.find(q=>q.id===workQuestion);}
function openFindings(q){return (q.text_review?.findings||[]).filter(f=>!f.dismissed);}
function activeWorkJob(){return data.jobs.find(j=>['running','queued'].includes(j.state)&&(j.document_ids?.includes(workDocument)||['proofread','explain'].includes(j.kind)&&JSON.parse(j.targets).some(id=>documentQuestions().some(q=>q.id===id))||j.kind==='reparse'&&JSON.parse(j.targets).includes(workDocument)));}
function jobInline(job){return `<div class="work-progress"><div class="row between"><strong>${esc(workLabels[job.kind]||'자료 처리')} 중</strong><span>${job.completed}/${job.total}건</span></div><p>${esc(job.detail)}</p><div class="progress"><span style="width:${job.total?100*job.completed/job.total:0}%"></span></div><small>처리가 끝나면 이 화면에 결과와 다음 버튼이 표시됩니다.</small></div>`;}
window.libraryGuidance=()=>{
 const job=followJob&&data.jobs.find(j=>j.id===followJob);
 if(job&&['queued','running'].includes(job.state))return jobInline(job);
 if(job&&job.state==='completed'&&job.failed)return `<div class="work-next warning"><div><strong>자료를 읽지 못했습니다</strong><p>${esc(job.detail)}</p></div>${btn('실패 항목 다시 처리','retry-job','primary',`data-id="${job.id}"`,'restore')}</div>`;
 const doc=data.documents.find(d=>!d.trashed);
 if(doc)return `<div class="work-next"><div><div class="eyebrow">이어서 할 작업</div><strong>${esc(doc.name)}</strong><p>분리 결과·검수·해설·시험지를 한 화면에서 순서대로 진행합니다.</p></div>${btn('자료 열고 다음 작업 보기','document-questions','primary',`data-id="${doc.id}"`,'arrow')}</div>`;
 return `<div class="start-guide"><div><b>1</b><strong>문제 파일 선택</strong><small>HWPX 또는 HWP · 답지는 선택</small></div><span>→</span><div><b>2</b><strong>자동 분리·검수 확인</strong><small>원문과 나란히 대조</small></div><span>→</span><div><b>3</b><strong>정답·해설 생성</strong><small>별도 풀이와 검사</small></div><span>→</span><div><b>4</b><strong>시험지 만들기</strong><small>PDF·HWPX로 저장</small></div></div><div class="work-next"><div><strong>처음에는 ‘자료 가져오기’ 하나만 누르세요.</strong><p>가져온 자료가 자동으로 열리고, 다음에 할 일을 안내합니다.</p></div>${btn('자료 가져오기','import','primary','','upload')}</div>`;
};

window.documentWorkflowView=()=>{
 if(!workDocument||!workSummary)return null;
 const s=workSummary,c=s.counts,qs=documentQuestions(),q=selectedWorkQuestion(),job=activeWorkJob();
 const done=[true,c.bundles===0,c.text_findings===0,c.solutions===c.questions&&c.questions>0];
 const steps=['자료 가져오기','문항 분리','원문·오타 검수','정답·해설','시험지 만들기'];
 const current=s.next_action==='reparse'||s.next_action==='boundaries'?1:s.next_action==='proofreading'?2:s.next_action==='explain'||s.next_action==='verification'?3:4;
 const nextButton={reparse:'원본에서 자동 재분리',boundaries:'자동 분리안 보기',proofreading:'의심 문구 확인',explain:'정답·해설 생성',verification:'보류 사유 확인',compose:'검사 통과 문항으로 시험지 만들기',exam:'만든 시험 열기'}[s.next_action];
 return `<div class="row work-back"><button class="link" data-action="work-library">← 자료실 목록</button><span>${esc(s.document.name)}</span></div>`+
 heading('가져온 자료 확인','화면 위의 다음 작업을 따라가세요. 다른 메뉴에서 버튼을 찾을 필요가 없습니다.',btn('단원별로 모아보기','work-units','','','questions')+btn('사용 순서','work-help','','','info'))+
 `<div class="work-steps">${steps.map((title,i)=>`<div class="${i===current?'active':done[i]?'done':''}"><b>${done[i]&&i!==current?'✓':i+1}</b><span>${title}</span></div>`).join('')}</div>`+
 (job?jobInline(job):`<div class="work-next ${['boundaries','reparse','proofreading','verification'].includes(s.next_action)?'warning':''}"><div><div class="eyebrow">지금 할 일 · ${current+1}단계</div><strong>${esc(s.next_title)}</strong><p>${esc(s.next_reason)}</p></div>${btn(nextButton,'work-next','primary','','arrow')}</div>`)+
 `<div class="work-counts"><span>분리 문항 <b>${c.questions}</b></span><span>객관식 <b>${c.mc}</b></span><span>단답형 <b>${c.short}</b></span><span>경계 확인 <b>${c.bundles}묶음</b></span><span>문장 의심 <b>${c.text_findings}건</b></span><span>사용 가능 <b>${c.ready}</b></span></div>`+
 documentClassificationTable(qs)+`<div class="work-layout"><aside class="work-list"><div class="work-list-title">문항 목록 <small>${qs.length}개</small></div>${qs.map((item,i)=>`<button class="work-question ${q?.id===item.id?'active':''}" data-action="work-select" data-id="${item.id}"><div><b>${item.source.boundary_review?'묶음':String(item.source.number??i+1).padStart(2,'0')}</b><span>${item.source.boundary_review?'분리안 확인':item.body.answer_format==='mc'?'객관식':'단답형'}</span></div><small>${item.source.boundary_review?'경계 확인 필요':openFindings(item).length?'문장 의심 '+openFindings(item).length+'건':item.available?'검사 통과':item.answer?.verification==='held'?'풀이 보류':item.answer?'해설 확인':'해설 미생성'}</small><span class="work-q-class">${esc(item.classification.subunit||item.classification.unit)} · ${questionEstimate(item)===null?'난이도 미분류':questionEstimate(item)+'/10'}</span></button>`).join('')}<button class="work-reparse link" data-action="work-reparse">자동 분리가 잘못되었나요?<br>원본에서 다시 분석</button>${s.has_repair_history?'<button class="link work-reparse" data-action="work-undo">이전 분리 결과로 되돌리기</button>':''}</aside>`+
 `<section class="work-content"><div class="work-content-head"><div><strong>${q?.source.boundary_review?'원문 묶음':q?'문항 '+(q.source.number??''):'문항 없음'}</strong><span>${q?stateBadge(q):''}</span></div><div class="tabs">${[['question','문제'],['source','원문과 대조'],['proofread','오타 검수'],['solution','정답·해설']].map(([key,label])=>`<button data-action="work-tab" data-tab="${key}" class="${workTab===key?'active':''}">${label}</button>`).join('')}</div></div><div class="work-main-body">${q?workQuestionContent(q):empty('문항을 선택하세요','왼쪽 목록에서 문항을 선택하면 본문과 검수 내용을 볼 수 있습니다.')}</div></section>`+
 `<aside class="work-inspector">${q?workInspector(q):''}</aside></div>`;
};
function workQuestionContent(q){
 if(workTab==='source'||workTab==='proofread'){
  const raw=sourceCache.get(q.id+':'+q.revision);
  return (workTab==='proofread'?proofreadPanel(q):'')+`<div class="source-compare"><section><h3>현재 저장 문항 <small>r${q.revision}</small></h3>${body(q)}</section><section class="source-original"><h3>원문 추출 <small>수정하지 않은 관리 원본</small></h3>${raw?`<div class="q-body">${blocks(raw.blocks)}</div>${raw.original_note?`<div class="condition-box"><strong>원본 각주·미주</strong>${blocks(raw.original_note.blocks)}</div>`:''}<p class="note">${esc(raw.message)}</p>`:'<p class="note">원문을 읽고 있습니다…</p>'}</section></div>`;
 }
 if(workTab==='solution'){
  const a=q.answer||{};
  if(!a.steps?.length)return `<div class="work-empty"><h3>정답·해설을 아직 생성하지 않았습니다</h3><p>문항은 이미 저장되어 있습니다. 원본 정답이 없어도 새로 풀 수 있습니다.</p>${btn('이 문항 정답·해설 생성','work-explain-one','primary','','spark')}</div>`;
  return `<div class="answer-callout"><small>정답 · ${esc(statusLabels[a.verification]||'미검증')}</small><strong>${a.final_mathml||esc(a.final_answer)}</strong></div>${a.verification!=='passed'?`<div class="callout">${esc(a.reason)}</div>`:''}${a.steps.map(step=>`<div class="step"><h4>${esc(step.title)}</h4><div class="q-body">${blocks(step.blocks)}</div></div>`).join('')}`;
 }
 return (q.source.boundary_review?`<div class="callout"><strong>아직 하나의 문항으로 확정한 상태가 아닙니다.</strong><br>자동으로 제안한 분리 위치를 먼저 보여 드립니다. 필요한 경우에만 조정하세요.<br>${btn('자동 분리안 보기','work-boundary','primary small','','edit')}</div>`:'')+body(q)+`<div class="work-bottom-actions">${btn('원문과 나란히 보기','work-source','','','file')}${btn('문항 수정','edit-question','',`data-id="${q.id}"`,'edit')}</div>`;
}
function workInspector(q){
 const r=q.text_review||{},a=q.answer||{},source=q.source;
 return classificationPanel(q)+`<h3>이 문항의 상태</h3><div class="work-state"><span>분리·저장</span>${badge(source.boundary_review?'경계 확인 필요':q.input_state==='complete'?'저장 완료':'입력 확인',source.boundary_review||q.input_state!=='complete'?'amber':'green')}</div><div class="work-state"><span>기본 자동검사</span>${badge(r.blocking?'깨진 문자':openFindings(q).length?'의심 '+openFindings(q).length+'건':'규칙 검사 완료',r.blocking?'red':openFindings(q).length?'amber':'green')}</div><div class="work-state"><span>정답·해설</span>${badge(a.steps?.length?'생성 완료':'미생성',a.steps?.length?'purple':'')}</div><div class="work-state"><span>수학 검증</span>${stateBadge(q)}</div><div class="work-state"><span>시험지 사용</span>${badge(q.available?'가능':'보류',q.available?'green':'amber')}</div>`+
 `<div class="work-inspector-note">${esc(q.available?'유형별 검사 조건을 충족했습니다. 시험지에 담을 수 있습니다.':source.boundary_review?'먼저 자동 분리안을 확인하세요.':a.reason||'정답·해설을 생성하면 별도 계산과 검증을 진행합니다.')}</div>`+
 `${(q.issues||[]).map(i=>`<div class="hold-block">${esc(i.reason)}</div>`).join('')}`+
 `<h3>원문·오타 검수</h3><p class="note">기본 검사는 깨진 문자·중복 문구·문장 부호 등을 찾습니다. ‘규칙 검사 완료’가 오타가 전혀 없다는 뜻은 아닙니다.</p>${btn('원문·오타 확인','work-proofread-tab','full small','','search')}${btn('AI 문장검수 · 선택','work-proofread-ai','full small','','spark')}`+
 `${r.ai_state==='failed'?`<div class="callout">AI 검수 실패<br>${esc(r.ai_error)}</div>`:r.ai_state==='completed'?`<p class="note">AI 문장검수 완료 · ${esc(r.ai_model||'설정 모델')} · 자동 수정 없음</p>`:'<p class="note">AI 문장검수는 아직 실행하지 않았습니다.</p>'}`+
 `${source.answer_ambiguity?'<div class="callout">원본 주석의 정답·해설 구분이 필요합니다. 원문과 대조 탭에서 확인하세요.'+btn('이 주석은 참고 설명','work-note-reference','small','','check')+'</div>':''}<h3>출처</h3><dl class="detail-list"><dt>원본 정답</dt><dd>${esc(q.original_answer||'미제공')}</dd><dt>저장 버전</dt><dd>r${q.revision}</dd><dt>분리 근거</dt><dd>${esc(({ 'answer-note':'문항 앞 번호 주석','dot':'본문 번호','paragraph-numbering':'문단 자동 번호','math-label':'번호 수식','label':'명시적 문항 표시','unresolved':'자동 확정 전'})[source.boundary_evidence]||'문서 구조')}</dd></dl>`;
}
function proofreadPanel(q){
 const r=q.text_review||{},findings=openFindings(q);
 return `<div class="proofread-head"><h3>의심 문구 ${findings.length}건</h3><div class="row">${btn('기본 검사 다시 실행','work-proofread-local','small','','search')}${btn('AI 문장검수','work-proofread-ai','small','','spark')}</div></div>`+
 (!findings.length?'<div class="callout">현재 자동 규칙에서 찾은 의심 문구는 없습니다. 문맥·수학적 의미의 모든 오타를 검사했다는 뜻은 아닙니다.</div>':findings.map(f=>`<div class="text-finding ${f.severity==='blocking'?'blocking':''}"><div class="row between">${badge(f.severity==='blocking'?'원문 확인 필요':'오타 의심',f.severity==='blocking'?'red':'amber')}<small>${f.origin==='ai'?'AI 제안':'자동 규칙'}</small></div><p>${esc(f.reason)}</p><div class="text-before">${esc(f.original)}</div>${f.suggestion!==null?`<div class="text-after">제안: ${esc(f.suggestion)}</div>`:''}<small>문맥: ${esc(f.context)}</small><div class="row">${btn('수정안 확인','work-correct','primary small',`data-finding="${f.id}"`,'edit')}${f.severity!=='blocking'?btn('원문 표현 유지','work-dismiss','small',`data-finding="${f.id}"`,'check'):''}</div></div>`).join(''))+
 `<p class="note">${esc(r.limitation||'원문을 보존하고 수정은 새 버전으로 기록합니다.')}</p>`;
}
async function suggestedBoundaryDialog(q){
 const proposal=await api('boundary_suggestions',{id:q.id});boundaryDialog(q.id);
 for(const index of proposal.starts){const input=document.querySelector(`[data-boundary-start="${index}"]`);if(input)input.checked=true;}
 const first=$('[data-boundary-start]');first?.dispatchEvent(new Event('change',{bubbles:true}));
 const note=document.createElement('div');note.className='callout';note.textContent=`자동 제안: ${proposal.starts.length}문항. ${proposal.reason} 체크된 위치는 수정할 수 있습니다.`;$('#modalLayer .modal-body').prepend(note);
 const save=$('[data-action="save-boundaries"]');if(save)save.textContent='이 분리안으로 저장';
}
window.workflowAction=async(action,el)=>{
 const q=selectedWorkQuestion();
 if(action==='work-library'){workDocument=null;workSummary=null;followJob=null;navigate('library');return true;}
 if(action==='work-help'){modal('사용 순서',`<ol class="work-help"><li><strong>자료 가져오기</strong><p>HWPX/HWP 문제 파일을 선택합니다. 답지는 없어도 됩니다.</p></li><li><strong>분리 결과 보기</strong><p>왼쪽에 객관식·단답형 문항이 나열됩니다. 숫자나 보기가 합쳐진 경우에만 자동 재분리를 사용합니다.</p></li><li><strong>원문·오타 확인</strong><p>의심 문구가 있으면 원문과 대조하고, 필요한 수정만 새 버전에 반영합니다.</p></li><li><strong>정답·해설 생성</strong><p>저장한 문항을 별도로 풀고 검사합니다. 검사 통과 문항만 시험지에 담습니다.</p></li><li><strong>시험지 만들기</strong><p>제목·배점 확인 후 확정하고 ‘출력’에서 PDF/HWPX를 저장합니다. 학생 배정 후 성적표에서 답안을 입력합니다.</p></li></ol>`);return true;}
 if(action==='work-select'){workQuestion=el.dataset.id;await window.workflowDataUpdated();renderPage();return true;}
 if(action==='work-tab'){workTab=el.dataset.tab;renderPage();return true;}
 if(action==='work-source'){workTab='source';renderPage();return true;}
 if(action==='work-proofread-tab'){workTab='proofread';renderPage();return true;}
 if(action==='work-next'){
  switch(workSummary.next_action){
   case'reparse':return window.workflowAction('work-reparse',el);
   case'boundaries':workQuestion=workSummary.first_boundary;await window.workflowDataUpdated();await suggestedBoundaryDialog(selectedWorkQuestion());return true;
   case'proofreading':workQuestion=workSummary.first_finding;workTab='proofread';await window.workflowDataUpdated();renderPage();return true;
   case'verification':workQuestion=workSummary.first_held||workQuestion;workTab='solution';renderPage();return true;
   case'explain':return window.workflowAction('work-explain-all',el);
   case'exam':lastCreatedExam=workSummary.last_exam_id;navigate('exams');return true;
   case'compose':selected=new Set(workSummary.ready_ids);examOptions.source_document_id=workDocument;examOptions.title=workSummary.document.name.replace(/\.[^.]+$/,'')+' · 시험';await runAction('compose-selected',el);return true;
  }
 }
 if(action==='work-boundary'){await suggestedBoundaryDialog(q);return true;}
 if(action==='work-reparse'){
  modal('원본에서 자동 재분리',`<p class="note">보존한 원본을 새 분리기로 다시 읽습니다. 현재 분리 결과와 수정 내역은 이전 이력에 보존하고, 확정 시험·성적은 바꾸지 않습니다.</p><p class="note">작업 후 ‘이전 분리 결과로 되돌리기’를 사용할 수 있습니다.</p>`,btn('자동 재분리 시작','work-reparse-go','primary','','restore'));return true;
 }
 if(action==='work-reparse-go'){await api('repair_document',{id:workDocument});closeModal();await refresh();return true;}
 if(action==='work-undo'){await api('undo_reparse',{id:workDocument});workQuestion=null;await refresh();toast('이전 분리 결과로 돌아왔습니다.');return true;}
 if(action==='work-explain-all'||action==='work-explain-one'){
  const ids=action==='work-explain-one'?[q.id]:workSummary.pending_ids;
  modal('정답·해설 생성',`<p class="note">${ids.length}문항을 별도로 풀고 원본 정답이 있으면 대조합니다. 원본 답지가 없어도 진행할 수 있습니다.</p><div class="field"><label>풀이 방법</label><select id="workExplainProvider"><option value="local">로컬 수학 계산 · 인터넷 없이 지원 유형 풀이</option><option value="ai">설정한 AI 모델 + 별도 재풀이·계산 대조</option></select></div><p class="note">계산 정책이나 도형 검증이 없는 문항은 보류 사유를 표시합니다.</p>`,btn('생성·검사 시작','work-explain-go','primary',`data-ids="${ids.join(',')}"`,'spark'));return true;
 }
 if(action==='work-explain-go'){await api('explain',{ids:el.dataset.ids.split(',').filter(Boolean),settings:$('#workExplainProvider').value==='local'?{provider:'local'}:data.settings.ai});closeModal();await refresh();return true;}
 if(action==='work-proofread-local'){await api('proofread',{ids:[q.id],settings:{provider:'local'}});await refresh();return true;}
 if(action==='work-proofread-ai'){
  modal('AI 문장검수',`<p class="note">선택한 문항의 일반 문장만 설정한 AI에 전달합니다. 모델 사용 한도·요금은 해당 연결 설정을 따릅니다.</p><p class="note">원문 인용과 위치가 일치하는 수정 제안만 저장하며 자동으로 고치지 않습니다. 수학 정답 검증과 별개입니다.</p>`,btn('AI 문장검수 시작','work-proofread-ai-go','primary','','spark'));return true;
 }
 if(action==='work-proofread-ai-go'){await api('proofread',{ids:[q.id],settings:data.settings.ai});closeModal();await refresh();return true;}
 if(action==='work-correct'){
  const f=q.text_review.findings.find(f=>f.id===el.dataset.finding);
  modal('수정안 확인',`<p class="note">${esc(f.reason)}</p><div class="field"><label>원문 문구 · 보존</label><textarea readonly>${esc(f.original)}</textarea></div><div class="field"><label>수정할 문구</label><textarea id="workReplacement">${esc(f.suggestion??'')}</textarea></div><div class="callout">원본 파일과 과거 시험은 보존합니다. 수정본 r${q.revision+1}을 저장하고 정답·해설은 다시 검사합니다.</div>`,btn('새 버전으로 반영','work-correct-go','primary',`data-finding="${f.id}"`,'save'));return true;
 }
 if(action==='work-correct-go'){el.disabled=true;await api('correct_text',{id:q.id,revision:q.revision,finding_id:el.dataset.finding,replacement:$('#workReplacement').value});closeModal();workTab='proofread';await refresh();toast('원문은 보존하고 수정본을 새 버전으로 저장했습니다.');return true;}
 if(action==='work-note-reference'){await api('resolve_source_note',{id:q.id,revision:q.revision});await refresh();return true;}
 if(action==='work-dismiss'){await api('dismiss_text',{id:q.id,revision:q.revision,finding_id:el.dataset.finding});await refresh();return true;}
 return false;
};
