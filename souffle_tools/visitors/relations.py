from dataclasses import dataclass
from typing import List, Tuple

from lark.visitors import Interpreter

from .utils import children_by_name


@dataclass(frozen=True)
class Relation:
    relname: str
    attrs: List[Tuple[str, str]]

    def __str__(self):
        return (
            self.relname
            + "("
            + ", ".join(f"{name}:{t}" for name, t in self.attrs)
            + ")"
        )


class RelationVisitor(Interpreter):
    """
    Collect all the relations in a Souffle program.

    This only looks at local declarations, hence if used in an input program with components,
    it can miss some relations.

    USE with the transformed Datalog from the compiler; relation declarations are qualified there.
    """

    def __init__(self):
        self.rels = {}

    def relation_decl(self, tree):
        relname = self.qualified_name(tree.children[0])
        assert isinstance(relname, str)

        attrs = []
        for attr in children_by_name(tree, "attribute"):
            attrs.append(self.attribute(attr))

        self.rels[relname] = Relation(relname, attrs)

    def attribute(self, tree) -> Tuple[str, str]:
        typename = tree.children[1]
        typename = self.visit(typename)
        assert isinstance(typename, str)
        return (str(tree.children[0]), typename)

    def number(self, tree) -> str:
        return "number"

    def symbol(self, tree) -> str:
        return "symbol"

    def unsigned(self, tree) -> str:
        return "unsigned"

    def float(self, tree) -> str:
        return "float"

    def qualified_name(self, tree) -> str:
        return ".".join(map(str, tree.children))
