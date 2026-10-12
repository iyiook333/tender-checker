import unittest

from app.schemas import LLMItem, ParsedDocument, DocumentSegment, SourceLocation, ResultCategory
from app.services.extractor import validate_and_merge


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.segment = DocumentSegment(
            source_id="line-1",
            text="投标截止时间：2026年10月20日17:00。",
            location=SourceLocation(source_id="line-1", line_start=1, line_end=1, label="第 1 行"),
            start_offset=0,
            end_offset=24,
        )
        self.document = ParsedDocument(filename="a.txt", media_type="text/plain", segments=[self.segment], total_characters=24)

    def test_matching_evidence_is_verified(self):
        item = LLMItem(category=ResultCategory.deadlines, title="投标截止时间", requirement="按时递交", evidence=self.segment.text, source_id="line-1", confidence=0.9)
        result = validate_and_merge([item], self.document)
        value = result["deadlines"][0]
        self.assertTrue(value.verified)
        self.assertEqual(value.location.label, "第 1 行")

    def test_split_source_id_maps_back_to_original_location(self):
        item = LLMItem(
            category=ResultCategory.deadlines,
            title="投标截止时间",
            requirement="按时递交",
            evidence="投标截止时间：2026年10月20日17:00。",
            source_id="line-1-part-1",
            confidence=0.9,
        )
        result = validate_and_merge([item], self.document)
        value = result["deadlines"][0]
        self.assertTrue(value.verified)
        self.assertEqual(value.source_id, "line-1-part-1")
        self.assertEqual(value.location.source_id, "line-1")


if __name__ == "__main__":
    unittest.main()
