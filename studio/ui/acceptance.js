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
  if(!workSummary||workSummary.counts.bundles!==1)return {ready:false};
  if(!document.querySelector('.work-next [data-action=work-next]'))return {ready:false};
  window.__guidedImport=true;
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
  if(click(`[data-action=report-export][data-id="${window.__guidedAttempt}"]`))return advance(20);break;
 case 20:
  if(!cfg.report)return {ready:false};
  return {ready:true,count:data.questions.length,nav:document.querySelectorAll('nav button').length,math:window.__mathCount,boundary_rows:window.__boundaryRows,boundary_saved:data.questions.filter(q=>q.source.profile==='user-selected-boundaries').length,guided_import:window.__guidedImport,proofread_correction:window.__proofreadFixed,score:reportData.score,maximum:reportData.maximum,exam:window.__guidedExam,attempt:window.__guidedAttempt};
 }
 return {ready:false,step:window.__guideStep};
})()
