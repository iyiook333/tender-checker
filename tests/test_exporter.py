import unittest

from app.schemas import ExtractedItem, ResultCategory
from app.services.exporter import result_csv


class ExporterTests(unittest.TestCase):
    def test_csv_neutralizes_formula_prefixes(self):
        items = [
            ExtractedItem(
                category=ResultCategory.materials,
                title="=HYPERLINK(\"http://example.test\")",
                requirement="+unsafe",
                evidence="-unsafe",
                source_id="line-1",
                severity="中",
                confidence=0.5,
                location=None,
            ),
        ]
        csv_text = result_csv({"materials": items})
        self.assertIn("'=HYPERLINK", csv_text)
        self.assertIn("'+unsafe", csv_text)
        self.assertIn("'-unsafe", csv_text)


if __name__ == "__main__":
    unittest.main()
