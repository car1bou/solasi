import unittest
from tests import test_answers
from lecture_study.answers import save_artifact
from lecture_study.jobs import submit_job
from lecture_study.models import Evidence
from lecture_study.outputs import export_markdown


class ExcerptExportTests(unittest.TestCase):
    setUp=test_answers.AnswerTests.setUp

    def test_source_excerpt_export_uses_selection_warning_without_ai_labels(self):
        evidence=Evidence(ref=self.ref,text='프로세스는 실행 중인 프로그램입니다.',label='노트')
        job=submit_job(self.db,self.sid,'ai',{'request':self.request.model_dump()})
        section={'title':'핵심 원문','text':evidence.text,'evidence_ids':[self.ref.id],'quotes':[{'text':evidence.text,'evidence_ids':[self.ref.id]}],'review_required':True,'subject':'잘못된 주어','event_type':'expectation'}
        saved=save_artifact(self.db,job['id'],{'summary_format':'excerpts-v1','sections':[section],'selection_incomplete_parts':[0]},[evidence],{'kind':'summary','provider':'ollama','model':'local','cutoff_ms':0,'retrieval_mode':'full_snapshot'})
        markdown=export_markdown(self.db,saved.id)
        self.assertIn(evidence.text,markdown);self.assertIn(self.ref.id,markdown)
        self.assertIn('구간 선택 확인 필요',markdown)
        self.assertNotIn('주어:',markdown);self.assertNotIn('기대',markdown);self.assertNotIn('생성 해석',markdown)
