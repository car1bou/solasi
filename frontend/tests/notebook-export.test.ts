import {test} from 'node:test';
import assert from 'node:assert/strict';
import {notebookExportIssue} from '../src/notebook-export.ts';
test('PDF export refuses unsaved hidden pages, conflicts and storage failures',()=>{
 const saved={page:1,loaded:true,status:'saved',storageError:''};
 assert.equal(notebookExportIssue([saved]),'');
 for(const status of ['loading','pending','saving','failed','conflict'])assert.match(notebookExportIssue([saved,{...saved,page:3,status}]),/3쪽/);
 assert.match(notebookExportIssue([{...saved,storageError:'failed'}]),/저장/);
});
