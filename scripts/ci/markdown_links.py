import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt


@dataclass
class Link:
    target: str
    line: int


@dataclass
class Document:
    anchors: set[str] = field(default_factory=set)
    links: list[Link] = field(default_factory=list)


class HtmlLinks(HTMLParser):
    def __init__(self, document: Document, line: int):
        super().__init__()
        self.document = document
        self.line = line

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if value is None:
                continue
            if key == "id" or (tag == "a" and key == "name"):
                self.document.anchors.add(value)
            if key == "href" or (tag == "img" and key == "src"):
                self.document.links.append(
                    Link(value, self.line + self.getpos()[0] - 1)
                )


def slug(text: str) -> str:
    text = re.sub(r"<[^>]*>", "", text).lower()
    return "".join(
        char for char in text if char in " -_" or unicodedata.category(char)[0] in "LNM"
    ).replace(" ", "-")


def parse_document(source: str) -> Document:
    document = Document()
    tokens = (
        MarkdownIt("commonmark").enable("table").enable("strikethrough").parse(source)
    )
    for index, token in enumerate(tokens):
        line = token.map[0] + 1 if token.map else 1
        if token.type == "heading_open":
            heading = tokens[index + 1]
            content = "".join(
                child.content
                for child in heading.children or []
                if child.type in {"text", "code_inline", "image", "html_inline"}
            )
            base = slug(content)
            anchor = base
            suffix = 0
            while anchor in document.anchors:
                suffix += 1
                anchor = f"{base}-{suffix}"
            document.anchors.add(anchor)
        if token.type == "html_block":
            HtmlLinks(document, line).feed(token.content)
        for child in token.children or []:
            if child.type == "link_open":
                document.links.append(Link(child.attrGet("href") or "", line))
            elif child.type == "image":
                document.links.append(Link(child.attrGet("src") or "", line))
            elif child.type == "html_inline":
                HtmlLinks(document, line).feed(child.content)
    return document


def check_links(root: Path, tracked: list[str]) -> list[str]:
    root = root.resolve()
    files = {(root / name).resolve() for name in tracked}
    directories = {
        parent
        for path in files
        for parent in path.parents
        if parent.is_relative_to(root)
    }
    documents = {
        path: parse_document(path.read_text(encoding="utf-8"))
        for path in files
        if path.suffix.lower() == ".md"
    }
    findings = []
    for path, document in sorted(documents.items()):
        for link in document.links:
            target = urlsplit(link.target)
            if target.scheme or target.netloc:
                continue
            destination = (
                (path.parent / unquote(target.path)).resolve() if target.path else path
            )
            if target.path.startswith("/"):
                destination = (root / unquote(target.path).lstrip("/")).resolve()
            problem = None
            if destination not in files and destination not in directories:
                problem = "target is absent from tracked files"
            elif target.fragment and destination in documents:
                anchor = unquote(target.fragment)
                if anchor not in documents[destination].anchors:
                    problem = "heading/HTML anchor is missing"
            if problem:
                findings.append(
                    f"{path.relative_to(root)}:{link.line}: {link.target}: {problem}"
                )
    return findings


def main() -> int:
    tracked = (
        subprocess.check_output(["git", "ls-files", "-z"], text=True)
        .rstrip("\0")
        .split("\0")
    )
    findings = check_links(Path("."), tracked)
    for finding in findings:
        print(finding)
    print(
        f"Markdown links: {sum(name.lower().endswith('.md') for name in tracked)} files, {len(findings)} findings"
    )
    return int(bool(findings))


if __name__ == "__main__":
    sys.exit(main())
