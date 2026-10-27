import test from 'node:test';
import assert from 'node:assert/strict';
import {sameQuestionContext} from '../src/question-jobs.ts';

test('an extra explanation restores only its own question and scope',()=>{
  const scope={course_id:'course',mode:'course',asset_id:'pdf',page:1,document_sha256:'digest'};
  const request={prompt:'CDF의 조건',scope:{...scope,session_id:null,lecture_ids:[]}};
  assert.equal(sameQuestionContext(request,'CDF의 조건',scope),true);
  assert.equal(sameQuestionContext(request,'작성자',scope),false);
  for(const changed of [{course_id:'other'},{asset_id:'other'},{page:2},{document_sha256:'revised'},{mode:'current'},{session_id:'lecture'},{lecture_ids:['previous']}]){
    assert.equal(sameQuestionContext(request,'CDF의 조건',{...scope,...changed}),false);
  }
  assert.equal(sameQuestionContext(request,'CDF의 조건',undefined),false);
});
