from dataclasses import dataclass
from typing import Dict, List, Optional

from lark.visitors import Interpreter

from .utils import has_child
from .relations import Relation


@dataclass
class PlanNode:
    text: str
    children: List["PlanNode"]
    debug_info: Optional[str] = None
    seperator: str = "\n"  # seperator character... use it in __str__
    trailer: Optional[str] = None  # trailer after children... use it in __str__

    def __str__(self, prefix="") -> str:
        return (
            prefix
            + self.text
            + "\n"
            + self.seperator.join(
                map(lambda x: x.__str__(prefix=prefix + "   "), self.children)
            )
            + (f"\n{self.trailer}" if self.trailer is not None else ""),
        )


class TextualPlanVisitor(Interpreter):
    def __init__(self, rels: Dict[str, Relation]):
        self.out = ""
        self._plan = None  # for gradully building plans BOTTOM UP.

    def program(self, tree) -> PlanNode:
        return PlanNode("PROGRAM", list(map(self.visit, tree.children[1:-1])))

    def subroutine(self, tree) -> PlanNode:
        return PlanNode(str(tree.children[0]), list(map(self.visit, tree.children[1:])))

    ### Subroutine statements

    def loop_stmt(self, tree):
        return PlanNode("FOR i : ℕ", list(map(self.visit, tree.children[1:])))

    def query_stmt(self, tree):
        # HACK: Things get non-local here. We expect the leaf that becomes root of self._plan to clean up after us.
        self._plan = PlanNode("", [])
        return self.visit(tree.children[0])

    def debug_stmt(self, tree):
        plan = self.visit(tree.children[1])
        plan.debug_info = str(tree.children[0])
        return plan

    def clear_stmt(self, tree):
        return PlanNode(f"{self.visit(tree.children[0])} = ∅", [])

    def swap_stmt(self, tree):
        rel1, rel2 = self.visit_children(tree)
        return PlanNode(f"{rel1}, {rel2} = {rel2}, {rel1}", [])

    def exit_stmt(self, tree):
        return PlanNode(f"BREAK {self.visit(tree.children[0])}", [])

    def io_stmt(self, tree):
        relname = self.visit(tree.children[0])
        io_options = dict(map(self.visit, tree.children[1:]))

        operation: str
        if io_options["operation"] == "input":
            operation = "Input from "
        elif io_options["operation"] == "output":
            operation = "Output to "
        else:
            raise RuntimeError(f"Unrecognized IO operation {io_options['operation']}")

        fname = ""
        if io_options["filename"].removesuffix(".dl") != relname:
            fname = f"fname {io_options['filename']}"

        return PlanNode(
            f"{operation} {relname} delim {repr(io_options['delimiter'])} {fname}", []
        )

    ### RAM statements

    def declare_stmt(self, tree):
        assert self._plan is not None

        tuple_element_ref = self.visit(tree.children[0])
        aggregator = self.visit(tree.children[1])
        tuple_name = str(tree.children[2])
        ram_relname = self.visit(tree.children[3])

        self._plan.children.append(
            PlanNode(
                f"{tuple_element_ref} = {aggregator}{{{tuple_name} ∈ {ram_relname}}}",
                [],
            )
        )

        return self.visit(tree.children[-1])

    def forloop(self, tree):
        assert self._plan is not None

        tuple_name = str(tree.children[0])
        ram_relname = self.visit(tree.children[1])

        # add index condition, if there is one.
        cond = ""
        if has_child(tree, "on_index"):
            cond = self.visit(tree.children[2])

        self._plan.children.append(
            PlanNode(f"{tuple_name} ∈ {ram_relname}, {cond}", [])
        )

        return self.visit(tree.children[-1])

    def if_stmt(self, tree):
        assert self._plan is not None

        # TODO: We currently don't handle if statements that break
        if not has_child(tree, "BREAK"):
            if_cond = self.visit(tree.children[0])

            # add index condition, if there is one.
            index_cond = ""
            if has_child(tree, "on_index"):
                index_cond = f" USING INDEX {self.visit(tree.children[2])}"

            self._plan.children.append(PlanNode(f"{if_cond}{index_cond}", []))

        return self.visit(tree.children[-1])

    def unpack_stmt(self, tree):
        assert self._plan is not None

        # TODO: Ideally we resolve ADT types here.
        iden = self.visit(tree.children[0])
        tuple_element_ref = self.visit(tree.children[2])

        self._plan.children.append(PlanNode(f"{iden} = {tuple_element_ref}", []))

        return self.visit(tree.children[-1])

    def insert_stmt(self, tree):
        assert self._plan is not None

        tuple_expr = self.visit(tree.children[0])
        ram_relname = self.visit(tree.children[1])

        self._plan.text = f"{ram_relname} = {ram_relname} ∪ {{{tuple_expr} | "
        self._seperator = ",\n"
        self._plan.trailer = "}"

        plan = self._plan

        # ... and we don't need this: other part of the non-local HACK.
        self._plan = None
        return plan

    def on_index(self, tree):
        return self.visit(tree.children[0])

    ### RAM conditions

    ### Building blocks

    def io_option(self, tree):
        return self.visit_children(tree)

    def tab_list(self, tree):
        return "\t".join(map(str, tree.children))

    def qualified_name(self, tree):
        return ".".join(map(str, tree.children))

    def object(self, tree):
        return dict(map(self.visit, tree.children))

    def array(self, tree):
        return list(map(self.visit, tree.children))

    def pair(self, tree):
        x = ""
        # HACK: We have to do this because of the weird format used in the RAM output.
        exec(f"x = {tree.children[0]}")
        return (x, self.visit(tree.children[1]))

    def string(self, tree):
        x = ""
        # HACK: We have to do this because of the weird format used in the RAM output.
        exec(f"x = {tree.children[0]}")
        return x

    def number(self, tree):
        return int(tree.children[0])

    def true(self, _):
        return True

    def false(self, _):
        return False

    def null(self, _):
        return None
