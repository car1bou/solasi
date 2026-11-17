import json
from pathlib import Path
import tempfile
import unittest
from lecture_study.db import open_db, new_id, now, create_session
from lecture_study import study_memory as memory


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.db = open_db(self.path)
        self.addCleanup(lambda: self.db.close())
        self.cid, self.other = new_id(), new_id()
        with self.db:
            for cid in (self.cid, self.other):
                self.db.execute('INSERT INTO courses VALUES (?,?,?,?)', (cid, '과목', '', now()))
        self.sid = create_session(self.db, 'lecture', '강의', self.cid, 1).id
        self.owner = memory.owner(self.db, course_id=self.cid)
        self.thread = memory.create_thread(self.db, self.owner)

    def add(self, text='20쪽까지 공부했고 독립과 상호배타가 헷갈려요'):
        return memory.add_user(self.db, self.thread['id'], self.owner, text, {'course_id': self.cid})

    def test_reopen_preserves_old_records_and_course_thread_from_lecture(self):
        self.add()
        self.db.close()
        self.db = open_db(self.path)
        owner = memory.owner(self.db, session_id=self.sid)
        self.assertEqual(owner['course_id'], self.cid)
        saved = memory.read_thread(self.db, self.thread['id'], owner)
        self.assertIn('독립과 상호배타', saved['messages'][0]['text'])
        self.assertEqual(self.db.execute('PRAGMA user_version').fetchone()[0], 20)
        self.assertEqual(self.db.execute('SELECT title FROM sessions WHERE id=?', (self.sid,)).fetchone()[0], '강의')

    def test_wrong_course_and_scope_are_rejected(self):
        wrong = memory.owner(self.db, course_id=self.other)
        with self.assertRaises(KeyError): memory.read_thread(self.db, self.thread['id'], wrong)
        with self.assertRaises(ValueError):
            memory.add_user(self.db, self.thread['id'], self.owner, '질문', {'course_id': self.other})

    def test_user_message_survives_failure_and_pagination_is_stable(self):
        for i in range(7): self.add(str(i))
        page = memory.read_thread(self.db, self.thread['id'], self.owner, limit=3)
        self.assertEqual([m['text'] for m in page['messages']], ['4', '5', '6'])
        earlier = memory.read_thread(self.db, self.thread['id'], self.owner, before=page['messages'][0]['ordinal'], limit=3)
        self.assertEqual([m['text'] for m in earlier['messages']], ['1', '2', '3'])
        self.assertTrue(earlier['has_more'])

    def test_extraction_requires_exact_user_quote_and_never_infers_mastery(self):
        msg = self.add()
        epoch = memory.epoch(self.db, self.owner)
        body = {'summary': '독립 개념을 복습 중', 'items': [
            {'kind': 'difficulty', 'text': '독립과 상호배타가 헷갈림', 'quote': '독립과 상호배타가 헷갈려요', 'message_id': msg['id'], 'status': 'active'}]}
        memory.apply_extraction(self.db, self.thread['id'], self.owner, epoch, [msg['id']], body)
        records = memory.memory_list(self.db, self.cid)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['quote'], body['items'][0]['quote'])
        body['items'][0]['quote'] = '완전히 이해했어'
        with self.assertRaises(ValueError):
            memory.apply_extraction(self.db, self.thread['id'], self.owner, epoch, [msg['id']], body)
        self.assertEqual(len(memory.memory_list(self.db, self.cid)), 1)

    def test_manual_edits_survive_extraction_and_clear_does_not_resurrect(self):
        msg = self.add()
        body = {'summary': '', 'items': [{'kind': 'difficulty', 'text': '독립이 어려움', 'quote': '독립과 상호배타가 헷갈려요', 'message_id': msg['id'], 'status': 'active'}]}
        memory.apply_extraction(self.db, self.thread['id'], self.owner, memory.epoch(self.db, self.owner), [msg['id']], body)
        item = memory.memory_list(self.db, self.cid)[0]
        memory.edit_memory(self.db, self.cid, item['id'], '이제 이해했어요', 'resolved', item['revision'])
        with self.assertRaisesRegex(ValueError, '변경'):
            memory.apply_extraction(self.db, self.thread['id'], self.owner, memory.epoch(self.db, self.owner), [msg['id']], body)
        self.assertEqual(memory.memory_list(self.db, self.cid)[0]['text'], '이제 이해했어요')
        old_epoch = memory.epoch(self.db, self.owner)
        memory.clear_memories(self.db, self.cid)
        self.assertFalse(memory.memory_list(self.db, self.cid))
        with self.assertRaisesRegex(ValueError, '변경'):
            memory.apply_extraction(self.db, self.thread['id'], self.owner, old_epoch, [msg['id']], body)
        self.assertIsNone(memory.next_extraction(self.db))
        self.assertEqual(len(memory.read_thread(self.db, self.thread['id'], self.owner)['messages']), 1)

    def test_deleting_conversation_removes_derived_memory_and_job_snapshots(self):
        from lecture_study.jobs import submit_job
        msg = self.add('내 비밀 학습 문장')
        body = {'summary': '내 비밀 학습 문장', 'items': [{'kind': 'topic', 'text': '내 비밀 학습 문장', 'quote': '내 비밀 학습 문장', 'message_id': msg['id'], 'status': 'active'}]}
        memory.apply_extraction(self.db, self.thread['id'], self.owner, memory.epoch(self.db, self.owner), [msg['id']], body)
        job = submit_job(self.db, None, 'study_chat', {'thread_id': self.thread['id'], 'history': [msg], 'prompt': msg['text']}, course_id=self.cid)
        memory.delete_thread(self.db, self.thread['id'], self.owner)
        self.assertFalse(memory.memory_list(self.db, self.cid))
        self.assertNotIn('내 비밀', self.db.execute('SELECT request FROM jobs WHERE id=?', (job['id'],)).fetchone()[0])

    def test_pause_excludes_history_and_invalidates_snapshots(self):
        self.add()
        old = memory.epoch(self.db, self.owner)
        memory.set_enabled(self.db, False)
        self.assertFalse(memory.enabled(self.db))
        self.assertNotEqual(old, memory.epoch(self.db, self.owner))
        self.assertIsNone(memory.next_extraction(self.db))
        self.assertEqual(len(memory.read_thread(self.db, self.thread['id'], self.owner)['messages']), 1)

    def test_session_delete_cleans_origin_turn_and_derived_memory(self):
        from lecture_study.lifecycle import delete_session
        lecture_owner = memory.owner(self.db, session_id=self.sid)
        thread = memory.create_thread(self.db, lecture_owner)
        msg = memory.add_user(self.db, thread['id'], lecture_owner, '회차 개인 내용', {'session_id': self.sid})
        body = {'summary': '회차 개인 내용', 'items': [{'kind': 'topic', 'text': '회차 개인 내용', 'quote': '회차 개인 내용', 'message_id': msg['id'], 'status': 'active'}]}
        memory.apply_extraction(self.db, thread['id'], lecture_owner, memory.epoch(self.db, lecture_owner), [msg['id']], body)
        delete_session(self.db, self.sid, True)
        self.assertFalse(memory.memory_list(self.db, self.cid))
        self.assertNotIn('회차 개인 내용', json.dumps(memory.read_thread(self.db, thread['id'], self.owner), ensure_ascii=False))

    def test_explicit_resolution_keeps_provenance_and_retires_old_automatic_difficulty(self):
        first = self.add('독립과 상호배타가 헷갈려요')
        memory.apply_extraction(self.db,self.thread['id'],self.owner,memory.epoch(self.db,self.owner),[first['id']],{'summary':'','items':[{'kind':'difficulty','text':'독립과 상호배타가 헷갈려요','quote':first['text'],'message_id':first['id'],'status':'active'}]})
        old = memory.memory_list(self.db,self.cid)[0]
        second = self.add('독립과 상호배타는 이제 이해했어요')
        memory.apply_extraction(self.db,self.thread['id'],self.owner,memory.epoch(self.db,self.owner),[second['id']],{'summary':'','items':[{'kind':'difficulty','text':second['text'],'quote':second['text'],'message_id':second['id'],'status':'resolved','replaces':old['id']}]})
        self.assertEqual(memory.memory_list(self.db,self.cid)[0]['status'],'resolved')
        self.assertNotIn('active',[r['status'] for r in memory.memory_list(self.db,self.cid)])

    def test_quiz_observation_uses_current_override_not_ability_inference(self):
        from lecture_study.jobs import submit_job
        job=submit_job(self.db,self.sid,'ai',{})
        aid,attempt=new_id(),new_id()
        with self.db:
            self.db.execute("INSERT INTO artifacts(id,job_id,session_id,kind,body,evidence,metadata,created_at) VALUES (?,?,?,'quiz',?,'[]','{}',?)",(aid,job['id'],self.sid,json.dumps({'questions':[{'id':'q','prompt':'독립 조건은?'}]}),now()))
            self.db.execute("INSERT INTO attempts(id,quiz_id,question_id,submitted_answer,grade,explanation,evidence_ids,metadata,status,created_at) VALUES (?,?,?,'답','incorrect','해설','[]','{}','done',?)",(attempt,aid,'q',now()))
        memory.sync_quizzes(self.db)
        self.assertIn('오답',memory.memory_list(self.db,self.cid)[0]['text'])
        with self.db:self.db.execute('INSERT INTO attempt_revisions VALUES (?,1,?,?,?)',(attempt,'correct','정정',now()))
        memory.sync_quizzes(self.db)
        self.assertIn('정답',memory.memory_list(self.db,self.cid)[0]['text'])
        self.assertNotIn('오답',memory.memory_list(self.db,self.cid)[0]['text'])
        memory.clear_memories(self.db,self.cid)
        memory.sync_quizzes(self.db)
        self.assertFalse(memory.memory_list(self.db,self.cid))


if __name__ == '__main__': unittest.main()
