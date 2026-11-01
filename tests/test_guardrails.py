import unittest

from app.agents.guardrails import validate_generated_content


class GeneratedContentValidationTests(unittest.TestCase):
    def test_accepts_complete_html(self):
        html = "<!DOCTYPE html><html lang='en'><head><title>Site</title><link rel='stylesheet' href='./style.css'></head><body><main>Hello</main><script src='./script.js'></script></body></html>"
        self.assertEqual(validate_generated_content("index.html", html)["status"], "passed")

    def test_rejects_incomplete_html(self):
        result = validate_generated_content("index.html", "<html><body>broken")
        self.assertEqual(result["status"], "blocked")

    def test_rejects_html_as_css(self):
        result = validate_generated_content("style.css", "<!DOCTYPE html><html></html>")
        self.assertEqual(result["status"], "blocked")

    def test_rejects_html_as_javascript(self):
        result = validate_generated_content("script.js", "<!DOCTYPE html><html><body>wrong</body></html>")
        self.assertEqual(result["status"], "blocked")

    def test_rejects_unbalanced_css(self):
        result = validate_generated_content("style.css", "body { color: red;")
        self.assertEqual(result["status"], "blocked")

    def test_accepts_basic_css_and_javascript(self):
        self.assertEqual(validate_generated_content("style.css", "body { color: red; }")["status"], "passed")
        self.assertEqual(validate_generated_content("script.js", "document.addEventListener('DOMContentLoaded', () => {});")["status"], "passed")


if __name__ == "__main__":
    unittest.main()
