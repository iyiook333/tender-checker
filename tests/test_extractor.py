import asyncio
import os
import tempfile
import unittest
from pathlib import Path

os.environ["CHECKER_MOCK_LLM"] = "1"

from app.services.document_parser import parse_document
from app.services.extractor import analyze_document
from app.services.llm_client import LLMClient


class ConcurrentClient:
    def __init__(self):
        self.current = 0
        self.maximum = 0

    async def extract(self, chunk):
        self.current += 1
        self.maximum = max(self.maximum, self.current)
        await asyncio.sleep(0.01)
        self.current -= 1
        return []


class ExtractorTests(unittest.TestCase):
    def test_chunk_requests_respect_concurrency_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "many.txt"
            path.write_text("材料要求\n" * 1200, encoding="utf-8")
            document = parse_document(path)
        client = ConcurrentClient()
        asyncio.run(analyze_document(document, client, max_chars=500, max_chunks=100, max_concurrency=2))
        self.assertLessEqual(client.maximum, 2)

    def test_mock_extracts_four_categories(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tender.txt"
            path.write_text(
                "资格条件：供应商应具有营业执照。\n"
                "无效投标：未按要求密封的投标文件将被否决。\n"
                "应提交材料：营业执照复印件和授权委托书。\n"
                "投标截止时间：2026年10月20日17:00。\n",
                encoding="utf-8",
            )
            document = parse_document(path)
        result = asyncio.run(analyze_document(document, LLMClient(), max_chars=500))
        self.assertTrue(result["qualification"])
        self.assertTrue(result["rejection"])
        self.assertTrue(result["materials"])
        self.assertTrue(result["deadlines"])
        self.assertTrue(all(item.verified for items in result.values() for item in items))


if __name__ == "__main__":
    unittest.main()
