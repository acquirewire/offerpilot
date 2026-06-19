"""A tiny stdlib DOM + CSS-ish selector engine for robust boost scraping.

Bookie boost pages defeat naive class matching two ways: class names are often
build-hashed (`BoostCard_root__a8F2x`, different every deploy) and the odds live
in an attribute (`aria-label="4/1"`, `data-odds="5.0"`) rather than text. So we
parse the page into a small node tree and match with a compact selector grammar:

    div                element name
    .foo               exact class token
    .Boost_root*       class PREFIX  (survives hashed-suffix CSS modules)
    #id                id equals
    [data-x]           has attribute
    [data-x=val]       attribute equals
    [data-x^=val]      attribute starts with
    [data-x*=val]      attribute contains
    span[data-x]       compound (all parts must match the node)
    ...::attr(name)    extract that attribute's value instead of the text
    ...::text          extract text (the default)

Stdlib only (html.parser). Tolerant of unclosed/void tags. Good enough for the
small, flat DOM of a boost card; not a general-purpose CSS engine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
         "link", "meta", "param", "source", "track", "wbr"}


@dataclass
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["Node"] = field(default_factory=list)
    parent: "Node | None" = None
    _text: str = ""                      # this node's own direct text only

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def text(self) -> str:
        """Collapsed text of this node and all descendants."""
        parts = [self._text] + [c.text() for c in self.children]
        return re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()

    def walk(self):
        for c in self.children:
            yield c
            yield from c.walk()


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node(tag="#root")
        self._stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag=tag, attrs={k: (v or "") for k, v in attrs}, parent=self._stack[-1])
        self._stack[-1].children.append(node)
        if tag not in _VOID:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = Node(tag=tag, attrs={k: (v or "") for k, v in attrs}, parent=self._stack[-1])
        self._stack[-1].children.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, 0, -1):       # tolerant: pop to match
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return

    def handle_data(self, data):
        if data.strip():
            self._stack[-1]._text += data


def parse(html: str) -> Node:
    b = _TreeBuilder()
    b.feed(html)
    return b.root


# --- selector ---------------------------------------------------------------

_PART = re.compile(
    r'(?P<tag>^[a-zA-Z][\w-]*)'
    r'|\.(?P<cls>[\w-]+)(?P<clsstar>\*)?'
    r'|#(?P<id>[\w-]+)'
    r'|\[(?P<attr>[\w:-]+)(?:(?P<op>[\^*]?=)"?(?P<val>[^\]"]*)"?)?\]'
    r'|::(?P<extract>attr\([\w:-]+\)|text)'
)


@dataclass
class Selector:
    raw: str
    tag: str | None = None
    classes: list[tuple[str, bool]] = field(default_factory=list)   # (name, is_prefix)
    id: str | None = None
    attrs: list[tuple[str, str, str]] = field(default_factory=list)  # (name, op, val)
    extract_attr: str | None = None        # None => text

    @classmethod
    def parse(cls, spec: str) -> "Selector":
        sel = cls(raw=spec)
        for m in _PART.finditer(spec.strip()):
            if m.group("tag"):
                sel.tag = m.group("tag")
            elif m.group("cls"):
                sel.classes.append((m.group("cls"), bool(m.group("clsstar"))))
            elif m.group("id"):
                sel.id = m.group("id")
            elif m.group("attr"):
                sel.attrs.append((m.group("attr"), m.group("op") or "", m.group("val") or ""))
            elif m.group("extract"):
                ex = m.group("extract")
                sel.extract_attr = ex[5:-1] if ex.startswith("attr(") else None
        return sel

    def matches(self, node: Node) -> bool:
        if node.tag.startswith("#"):
            return False
        if self.tag and node.tag != self.tag:
            return False
        if self.id and node.attrs.get("id") != self.id:
            return False
        ncls = node.classes
        for name, is_prefix in self.classes:
            if is_prefix:
                if not any(c.startswith(name) for c in ncls):
                    return False
            elif name not in ncls:
                return False
        for name, op, val in self.attrs:
            if name not in node.attrs:
                return False
            av = node.attrs[name]
            if op == "=" and av != val:
                return False
            if op == "^=" and not av.startswith(val):
                return False
            if op == "*=" and val not in av:
                return False
        return True

    def value(self, node: Node) -> str | None:
        if self.extract_attr is not None:
            return node.attrs.get(self.extract_attr)
        return node.text()


def find_all(root: Node, spec: str) -> list[Node]:
    sel = Selector.parse(spec)
    return [n for n in root.walk() if sel.matches(n)]


def first_value(card: Node, spec: str) -> str | None:
    """Text (or attribute value) of the first node under `card` matching `spec`."""
    sel = Selector.parse(spec)
    if sel.matches(card):
        return sel.value(card)
    for n in card.walk():
        if sel.matches(n):
            return sel.value(n)
    return None
