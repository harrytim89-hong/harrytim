import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from quiz_app.core import Question, load_questions, save_questions, select_questions


class QuizTests(unittest.TestCase):
    def setUp(self):
        self.question = Question("1 + 1?", ["1", "2"], 2, "덧셈")

    def test_grading(self):
        self.assertTrue(self.question.is_correct(2))
        self.assertFalse(self.question.is_correct(1))

    def test_invalid_question(self):
        for answer in (0, 3, True, "2"):
            with self.assertRaises(ValueError):
                Question("문제", ["A", "B"], answer)

    def test_storage_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "questions.json"
            self.assertEqual(load_questions(path), [])
            save_questions(path, [self.question])
            self.assertEqual(load_questions(path), [self.question])
            path.write_text('{"invalid": true}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_questions(path)

    def test_selection_without_replacement(self):
        questions = [Question(str(i), ["A", "B"], 1) for i in range(5)]
        selected = select_questions(questions, 5)
        self.assertEqual(len({q.prompt for q in selected}), 5)
        for count in (0, 6):
            with self.assertRaises(ValueError):
                select_questions(questions, count)

    def test_cli_add_and_quiz(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "questions.json"
            command = [sys.executable, "-m", "quiz_app", "--data", str(path)]
            added = subprocess.run(command + ["add"], input="1 + 1?\n2\n1\n2\n2\n덧셈\n",
                                   text=True, capture_output=True)
            self.assertEqual(added.returncode, 0, added.stdout + added.stderr)
            played = subprocess.run(command + ["quiz", "--count", "1"], input="x\n9\n2\n",
                                    text=True, capture_output=True)
            self.assertEqual(played.returncode, 0, played.stdout + played.stderr)
            self.assertIn("결과: 1/1 (100%)", played.stdout)
            self.assertEqual(len(json.loads(path.read_text())), 1)


if __name__ == "__main__":
    unittest.main()
