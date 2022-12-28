from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Dict, List, Tuple

from lark.visitors import Interpreter

from .utils import has_child, children_by_name
from .relations import Relation


@dataclass(frozen=True)
class SouffleBTreeIndex:
    relname: str
    attrs: List[Tuple[str, str]]

    def index_type_str(self) -> str:
        return "\tBTREE(" + ", ".join(f"{name}:{t}" for name, t in self.attrs) + ")"

    def __str__(self) -> str:
        return (
            f"BTree Index on {self.relname}("
            + ", ".join(f"{name}:{t}" for name, t in self.attrs)
            + ")"
        )


class IndexVisitor(Interpreter):
    def __init__(self, rels: Dict[str, Relation]):
        self.indexes = defaultdict(lambda: [])
        self.rels = rels
        self._tuple_name = None
        self._tuple_attrs = set()

    def _add_index(self, tuple_name, relname, on_index):
        # track this tuple in the ram_cond
        self._tuple_name = tuple_name

        assert isinstance(self._tuple_attrs, Iterable)
        assert relname in self.rels

        # visit index condition to gather attributes in the index.
        self.visit(on_index)
        attrs = list(
            map(self.rels[relname].attrs.__getitem__, sorted(self._tuple_attrs))
        )

        self.indexes[relname].append(SouffleBTreeIndex(relname, attrs))

        # reset tuple_name. NOTE: Can I use context managers here?
        self._tuple_name = None
        self._tuple_attrs = set()

    def forloop(self, tree):
        if has_child(tree, "on_index"):
            tuple_name = str(tree.children[0])
            relname = self.visit(tree.children[1])
            on_index = tree.children[2]
            self._add_index(tuple_name, relname, on_index)

        self.visit(tree.children[-1])

    def tuple_element_ref(self, tree):
        if self._tuple_name == str(tree.children[0]):
            self._tuple_attrs.add(int(tree.children[1]))

    def ram_relname(self, tree) -> str:
        return self.visit(next(children_by_name(tree, "qualified_name")))

    def qualified_name(self, tree) -> str:
        return ".".join(map(str, tree.children))
