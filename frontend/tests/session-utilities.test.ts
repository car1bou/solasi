import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

test('compact desktop stacks hint cards before the sidebar leaves two narrow columns',()=>{
  const css=readFileSync(new URL('../src/styles.css',import.meta.url),'utf8');
  const compact=css.split('@media(max-width:700px){').at(-1)?.split('@media(max-width:600px){')[0]??'';
  assert.match(compact,/\.session-utilities>\.card\{min-width:100%\}/);
});
