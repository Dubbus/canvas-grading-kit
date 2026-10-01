#!/usr/bin/env python3
"""Small stdlib-only HTML -> Markdown converter for Canvas rich-text bodies."""
import re
from html.parser import HTMLParser

_BLOCK = {"p", "div", "section", "article", "blockquote", "table", "tr"}
_HEAD = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}


class _MD(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.lists = []      # stack of ["ul"|"ol", counter]
        self.href = None
        self.pre = False

    def _nl(self, n=2):
        self.out.append("\n" * n)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in _BLOCK:
            self._nl()
        elif tag in _HEAD:
            self._nl()
            self.out.append(_HEAD[tag] + " ")
        elif tag == "br":
            self.out.append("  \n")
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("_")
        elif tag == "code" and not self.pre:
            self.out.append("`")
        elif tag == "pre":
            self.pre = True
            self._nl()
            self.out.append("```\n")
        elif tag in ("ul", "ol"):
            self.lists.append([tag, 0])
            self._nl(1)
        elif tag == "li":
            indent = "  " * (len(self.lists) - 1)
            if self.lists and self.lists[-1][0] == "ol":
                self.lists[-1][1] += 1
                self.out.append(f"\n{indent}{self.lists[-1][1]}. ")
            else:
                self.out.append(f"\n{indent}- ")
        elif tag == "a":
            self.href = a.get("href")
            self.out.append("[")
        elif tag == "img":
            self.out.append(f"![{a.get('alt', '')}]({a.get('src', '')})")
        elif tag in ("td", "th"):
            self.out.append(" | ")

    def handle_endtag(self, tag):
        if tag in _BLOCK or tag in _HEAD:
            self._nl()
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("_")
        elif tag == "code" and not self.pre:
            self.out.append("`")
        elif tag == "pre":
            self.pre = False
            self.out.append("\n```")
            self._nl()
        elif tag in ("ul", "ol"):
            if self.lists:
                self.lists.pop()
            self._nl()
        elif tag == "a":
            self.out.append(f"]({self.href})" if self.href else "]")
            self.href = None

    def handle_data(self, data):
        self.out.append(data if self.pre else re.sub(r"\s+", " ", data))


def html_to_markdown(html):
    p = _MD()
    p.feed(html or "")
    p.close()
    text = "".join(p.out)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"
