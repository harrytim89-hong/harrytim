// Executed only by --self-test, with newly authored documents and fake students.
(()=>{
 if(typeof bridge==='undefined'||!bridge||!data.questions.length)return {ready:false};
 window.__guideStep=window.__guideStep||0;
 const click=(selector)=>{const el=document.querySelector(selector);if(!el)return false;el.click();return true;};
 const advance=(n)=>{window.__guideStep=n;return {ready:false,step:n};};
 const cfg=window.__guideFiles||{};
 switch(window.__guideStep){
 case 0:
  if(data.questions.length!==4)return {ready:false};
  if(click('[data-action=import]'))return advance(1);break;
 case 1:
  if(page!=='questions'||!document.querySelector('.pending-questions'))return {ready:false};
  if(document.querySelectorAll('.q-card').length!==0)return {error:'미분리 원문을 개별 문항으로 표시했습니다',step:1};
  window.__guidedImport=true;
  if(click('[data-action=pending-document]'))return advance(28);break;
 case 28:
  if(!workSummary||workSummary.counts.bundles!==1)return {ready:false};
  if(click('.work-next [data-action=work-next]'))return advance(2);break;
 case 2:
  if(!document.querySelector('[data-action=save-boundaries]'))return {ready:false};
  window.__boundaryRows=document.querySelectorAll('[data-boundary-start]').length;
  if(document.querySelectorAll('[data-boundary-start]:checked').length!==2)return {error:'자동 분리 제안이 2문항이 아닙니다',step:2};
  if(click('[data-action=save-boundaries]'))return advance(3);break;
 case 3:
  if(data.questions.length!==6||!workSummary||workSummary.counts.bundles!==0)return {ready:false};
  if(!document.querySelector('#modalLayer').classList.contains('hidden'))return {ready:false};
  if(workSummary.next_action!=='proofreading')return {error:'문장 의심 다음 안내가 없습니다',step:3};
  if(click('.work-next [data-action=work-next]'))return advance(4);break;
 case 4:
  if(!document.querySelector('.source-compare')||!document.querySelector('.text-finding'))return {ready:false};
  window.__mathCount=document.querySelectorAll('math').length;
  if(click('[data-action=work-correct]'))return advance(5);break;
 case 5:
  if(click('[data-action=work-correct-go]'))return advance(6);break;
 case 6:
  if(!workSummary||workSummary.counts.text_findings!==0||!document.querySelector('#modalLayer').classList.contains('hidden'))return {ready:false};
  const changed=data.questions.find(q=>q.source.text_correction);
  if(!changed||changed.revision!==2||changed.search_text.includes('??'))return {error:'오타 수정이 새 버전으로 반영되지 않았습니다',step:6};
  if(!document.querySelector('.source-original').innerText.includes('??'))return {error:'수정 전 원문이 보존되지 않았습니다',step:6};
  window.__proofreadFixed=true;
  if(click('.work-next [data-action=work-next]'))return advance(7);break;
 case 7:
  if(click('[data-action=work-explain-go]'))return advance(8);break;
 case 8:
  if(!workSummary||workSummary.counts.ready!==2||activeWorkJob())return {ready:false};
  if(click('.work-next [data-action=work-next]'))return advance(9);break;
 case 9:
  if(page!=='exams'||composer.length!==2)return {ready:false};
  const title=document.querySelector('[data-exam-option=title]');if(!title)return {ready:false};
  title.value='화면 전체 흐름 검증';title.dispatchEvent(new Event('change',{bubbles:true}));
  if(click('[data-action=confirm-exam]'))return advance(10);break;
 case 10:
  const exam=data.exams.find(e=>e.title==='화면 전체 흐름 검증'&&e.status==='confirmed');if(!exam)return {ready:false};
  window.__guidedExam=exam.id;
  if(click(`[data-action=export-dialog][data-id="${exam.id}"]`))return advance(11);break;
 case 11:
  if(click('[data-action=do-export]'))return advance(12);break;
 case 12:
  if(!cfg.exam||!document.querySelector('#modalLayer').classList.contains('hidden'))return {ready:false};
  navigate('students');if(click('[data-action=add-student]'))return advance(13);break;
 case 13:
  const form=document.querySelector('#studentForm');if(!form)return {ready:false};
  form.elements.name.value='화면 검증 학생';form.elements.school.value='검증 학교';form.elements.grade.value='1학년';form.elements.class_name.value='검증반';
  if(click('[data-action=save-student]'))return advance(14);break;
 case 14:
  const student=data.students.find(s=>s.name==='화면 검증 학생');if(!student)return {ready:false};
  window.__guidedStudent=student.id;navigate('exams');
  if(click(`[data-action=assign-dialog][data-id="${window.__guidedExam}"]`))return advance(15);break;
 case 15:
  const checkbox=document.querySelector(`[name=assignStudent][value="${window.__guidedStudent}"]`);if(!checkbox)return {ready:false};checkbox.checked=true;
  if(click('[data-action=do-assign]'))return advance(16);break;
 case 16:
  const attempt=data.attempts.find(a=>a.exam_id===window.__guidedExam&&a.student_id===window.__guidedStudent);if(!attempt)return {ready:false};
  window.__guidedAttempt=attempt.id;navigate('reports');
  if(click(`[data-action=open-report][data-id="${attempt.id}"]`))return advance(17);break;
 case 17:
  if(!reportData||reportData.attempt.id!==window.__guidedAttempt)return {ready:false};
  if(click(`[data-action=grade-dialog][data-id="${window.__guidedAttempt}"]`))return advance(18);break;
 case 18:
  if(!document.querySelector('[data-action=do-grade]'))return {ready:false};
  for(const item of reportData.items){const input=document.querySelector(`[data-submitted="${item.id}"]`);if(!input)return {ready:false};input.value=item.snapshot.answer.final_answer;}
  if(click('[data-action=do-grade]'))return advance(19);break;
 case 19:
  if(!reportData||reportData.attempt.state!=='graded'||reportData.score!==10||reportData.maximum!==10)return {ready:false};
  const comment=document.querySelector('#reportComment');if(!comment)return {error:'교사 코멘트 입력란이 없습니다',step:19};
  comment.value='조건을 식으로 표현하는 과정이 좋아졌습니다. 다음 시간에는 풀이를 설명해 봅시다.';
  if(click('[data-action=save-report-comment]'))return advance(33);break;
 case 33:
  if(reportData.comment!=='조건을 식으로 표현하는 과정이 좋아졌습니다. 다음 시간에는 풀이를 설명해 봅시다.')return {ready:false};
  window.__reportCommentSaved=true;
  if(click(`[data-action=report-export][data-id="${window.__guidedAttempt}"]`))return advance(20);break;
 case 20:
  if(!cfg.report)return {ready:false};
  navigate('library');
  if(document.querySelectorAll('.document-classifications tbody tr').length!==2)return {error:'자료의 문항별 분류표가 없습니다',step:20};
  if(click('[data-action=work-units]'))return advance(21);break;
 case 21:
  if(page!=='questions'||!document.querySelector('.unit-browser'))return {ready:false};
  if(unitFilteredQuestions().length!==2)return {error:'자료 안의 문항 범위가 다릅니다',step:21};
  const unitButton=[...document.querySelectorAll('.unit-tree-child')].find(b=>b.dataset.subunit==='다항식의 연산');
  if(!unitButton)return {error:'세부단원별 문항 목록이 없습니다',step:21};unitButton.click();return advance(22);
 case 22:
  const unitQuestions=unitFilteredQuestions();
  if(unitQuestions.length!==1||questionEstimate(unitQuestions[0])!==3)return {error:'단원 선택에 다른 단원의 문항이 섞였습니다',step:22};
  window.__unitQuestion=unitQuestions[0].id;window.__unitBefore=JSON.stringify(unitQuestions[0].body);
  const band=document.querySelector('[data-filter=band]');band.value='high';band.dispatchEvent(new Event('change',{bubbles:true}));return advance(23);
 case 23:
  if(unitFilteredQuestions().length!==0||document.querySelectorAll('.q-card').length!==0)return {error:'개별 문항 난이도 필터가 적용되지 않았습니다',step:23};
  filters.band='';renderPage();
  if(click(`[data-action=detail][data-id="${window.__unitQuestion}"]`))return advance(24);break;
 case 24:
  if(!document.querySelector('.drawer .question-classification')&&!document.querySelector('#drawer .question-classification'))return {ready:false};
  if(click(`#drawer [data-action=edit-classification][data-id="${window.__unitQuestion}"]`))return advance(25);break;
 case 25:
  const classForm=document.querySelector('#classificationForm');if(!classForm)return {ready:false};
  classForm.elements.unit.value='수업용 단원';classForm.elements.subunit.value='기본 연산';classForm.elements.type.value='직접 대입';classForm.elements.difficulty.value='2';classForm.elements.reason.value='이 문항의 대입·동류항 정리를 확인했습니다.';
  if(click('[data-action=save-classification]'))return advance(26);break;
 case 26:
  const moved=data.questions.find(q=>q.id===window.__unitQuestion);
  if(!moved||moved.difficulty!==2||!document.querySelector('#modalLayer').classList.contains('hidden'))return {ready:false};
  if(!moved.available||JSON.stringify(moved.body)!==window.__unitBefore)return {error:'분류 수정이 본문·정답 검증을 변경했습니다',step:26};
  if(reportData.items.find(i=>i.question_id===moved.id)?.snapshot.difficulty!==3)return {error:'분류 수정이 과거 시험의 난이도를 변경했습니다',step:26};
  closeDrawer();const scope=document.querySelector('[data-filter=document]');scope.value='';scope.dispatchEvent(new Event('change',{bubbles:true}));
  const movedUnit=[...document.querySelectorAll('.unit-tree-parent')].find(b=>b.dataset.unit==='수업용 단원');
  if(!movedUnit)return {error:'수정한 문항의 새 단원이 목록에 없습니다',step:26};movedUnit.click();return advance(27);
 case 27:
  if(unitFilteredQuestions().length!==1||unitFilteredQuestions()[0].id!==window.__unitQuestion||document.querySelectorAll('.q-card').length!==1)return {error:'전체 자료에서 새 단원의 개별 문항을 찾지 못했습니다',step:27};
  if(click(`[data-action=question-file][data-id="${window.__unitQuestion}"]`))return advance(29);break;
 case 29:
  if(click('[data-action=question-file-go]'))return advance(30);break;
 case 30:
  if(!cfg.single||!document.querySelector('#modalLayer').classList.contains('hidden'))return {ready:false};
  const individualIds=data.questions.filter(q=>q.document_id===workDocument&&!q.source.boundary_review).map(q=>q.id);
  filters={search:'',unit:'',state:'',difficulty:'',document:workDocument};renderPage();
  if(individualIds.length!==2||document.querySelectorAll('.q-card').length!==2)return {error:'문항 하나당 카드 하나가 아닙니다',step:30};
  for(const id of individualIds){const box=document.querySelector(`[data-select="${id}"]`);box.checked=true;box.dispatchEvent(new Event('change',{bubbles:true}));}
  if(click('[data-action=question-files]'))return advance(31);break;
 case 31:
  if(click('[data-action=question-file-go]'))return advance(32);break;
 case 32:
  if(!cfg.archive||!document.querySelector('#modalLayer').classList.contains('hidden'))return {ready:false};
  filters={search:'',unit:'',state:'',difficulty:''};renderPage();
  if(click('[data-action=school-filter][data-level="중등"]'))return advance(34);break;
 case 34:
  if(unitFilteredQuestions().some(q=>!['중등','중·고 공통'].includes(q.school_level)))return {error:'중등 범위에 고등 전용 문항이 섞였습니다',step:34};
  filters.school='';renderPage();
  const parent=data.questions.find(q=>data.questions.some(child=>child.lineage?.parent_id===q.id));
  if(!parent)return {error:'유사 문항 검증 원본이 없습니다',step:34};
  window.__similarSource=parent.id;composer=[{id:parent.id,points:7}];
  if(click(`[data-action=similar-questions][data-id="${parent.id}"]`))return advance(35);break;
 case 35:
  if(!document.querySelector('.similar-item'))return {ready:false};
  if(click('.similar-item [data-action=compare-questions]'))return advance(36);break;
 case 36:
  if(document.querySelectorAll('.question-compare>section').length!==2)return {ready:false};
  const replace=document.querySelector('[data-action=replace-similar]');if(!replace)return {error:'유사 문항 교체 버튼이 없습니다',step:36};
  window.__similarTarget=replace.dataset.id;replace.click();return advance(37);
 case 37:
  if(page!=='exams'||composer[0]?.id!==window.__similarTarget)return {ready:false};
  if(composer.length!==1||composer[0].points!==7)return {error:'유사 문항 교체가 배점이나 문항 수를 바꾸었습니다',step:37};
  window.__similarityChecked=true;selected.clear();filters={search:'',unit:'',state:'',difficulty:''};navigate('questions');return advance(38);
 case 38:
  return {ready:true,similarity:window.__similarityChecked,report_comment:window.__reportCommentSaved,individual_cards:true,question_files:true,count:data.questions.length,nav:document.querySelectorAll('nav button').length,math:window.__mathCount,boundary_rows:window.__boundaryRows,boundary_saved:data.questions.filter(q=>q.source.profile==='user-selected-boundaries').length,guided_import:window.__guidedImport,proofread_correction:window.__proofreadFixed,unit_navigation:true,question_classification:true,score:reportData.score,maximum:reportData.maximum,exam:window.__guidedExam,attempt:window.__guidedAttempt};
 }
 return {ready:false,step:window.__guideStep};
})()
