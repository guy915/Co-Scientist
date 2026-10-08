import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.ci.markdown_links import check_links, parse_document


class MarkdownLinksTests(unittest.TestCase):
    def test_github_heading_anchors_include_unicode_code_and_duplicate_suffixes(self):
        doc = parse_document(
            "# Héllo `world`!\n# Repeat\n# Repeat\n# Repeat-1\n<a id='custom'></a>\n"
        )
        self.assertEqual(
            doc.anchors, {"héllo-world", "repeat", "repeat-1", "repeat-1-1", "custom"}
        )

    def test_inline_reference_images_html_and_nested_parentheses_are_checked(self):
        doc = parse_document(
            "[one](a(b).md#heading) ![two](img.png) [three][ref]\n\n[ref]: b.md\n<a href='c.md#anchor'>link</a>\n<img src='d.png'>\n"
        )
        self.assertEqual(
            {link.target for link in doc.links},
            {"a(b).md#heading", "img.png", "b.md", "c.md#anchor", "d.png"},
        )

    def test_code_examples_do_not_create_links_or_headings(self):
        doc = parse_document(
            "```md\n# fake\n[bad](missing.md)\n```\n\n`[bad](missing.md)`\n\n    [bad](missing.md)\n"
        )
        self.assertFalse(doc.links)
        self.assertFalse(doc.anchors)

    def test_all_relative_targets_and_anchors_resolve_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "doc space.md").write_text(
                "Heading\n=======\n\n<a name='manual'></a>\n"
            )
            (root / "README.md").write_text(
                "[one](doc%20space.md#heading) [two](#local) [three](doc%20space.md#manual)\n# Local\n[remote](https://invalid.example/no-such-page)\n"
            )
            with patch(
                "urllib.request.urlopen",
                side_effect=AssertionError("network forbidden"),
            ):
                self.assertEqual(check_links(root, ["README.md", "doc space.md"]), [])

    def test_missing_files_untracked_files_and_missing_anchors_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "other.md").write_text("# Existing\n")
            (root / "ignored.md").write_text("# Ignored\n")
            (root / "README.md").write_text(
                "[one](missing.md) [two](other.md#absent) [three](ignored.md)\n"
            )
            findings = check_links(root, ["README.md", "other.md"])
            self.assertEqual(len(findings), 3)
            self.assertIn("missing.md", findings[0])
            self.assertIn("absent", findings[1])
            self.assertIn("ignored.md", findings[2])

    def test_directory_link_resolves_tracked_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "docs/a.md").write_text("# A")
            (root / "README.md").write_text("[docs](docs/)")
            self.assertEqual(check_links(root, ["README.md", "docs/a.md"]), [])


if __name__ == "__main__":
    unittest.main()
