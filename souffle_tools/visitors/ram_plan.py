from dataclasses import dataclass
from typing import Dict, List, Optional

import lark.tree
import lark.lexer
from lark.visitors import Interpreter

from .utils import has_child
from .relations import Relation


@dataclass
class PlanNode:
    text: str
    children: List["PlanNode"]
    debug_info: Optional[str] = None
    seperator: str = ""
    trailer: Optional[str] = None

    def __str__(self, prefix="") -> str:
        return (
            prefix
            + self.text
            + "\n"
            + f"{self.seperator}\n".join(
                map(
                    lambda x: x.__str__(prefix=prefix + "   ").removesuffix("\n"),
                    self.children,
                )
            )
            + (f"\n{prefix}{self.trailer}" if self.trailer is not None else "")
        )


class TextualPlanVisitor(Interpreter):
    def __init__(self, rels: Dict[str, Relation]):
        self.out = ""
        self._plan = None  # for gradully building plans BOTTOM UP.
        self.rels = rels
        self._bound_tuples = {}

    def _safe_visit(self, tree: lark.tree.Tree | lark.lexer.Token):
        if isinstance(tree, lark.tree.Tree):
            return self.visit(tree)
        else:
            return str(tree)

    def program(self, tree) -> PlanNode:
        def extract_stratum_number(stratum_plan_node: PlanNode) -> int:
            # bit of a HACK: depends on stratum names used by the souffle compiler.
            return int(stratum_plan_node.text.split("_")[1])

        return PlanNode(
            "PROGRAM",
            sorted(map(self.visit, tree.children[1:-1]), key=extract_stratum_number),
        )

    def subroutine(self, tree) -> PlanNode:
        return PlanNode(
            str(tree.children[0]),
            list(map(self.visit, tree.children[1:])),
            seperator=";",
        )

    ### Subroutine statements

    def loop_stmt(self, tree):
        return PlanNode("FOR i ∈ ℕ", list(map(self.visit, tree.children[1:])))

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
            operation = "INPUT FROM"
        elif io_options["operation"] == "output":
            operation = "OUTPUT TO"
        else:
            raise RuntimeError(f"Unrecognized IO operation {io_options['operation']}")

        fname = ""
        if io_options.get("filename", relname).removesuffix(".dl") != relname:
            fname = f" fname {io_options['filename']}"

        delim = repr(io_options.get("delimiter", "\t"))

        return PlanNode(f"{operation} {relname} delim {delim}{fname}", [])

    ### RAM statements

    def declare_stmt(self, tree):
        assert self._plan is not None

        tuple_element_ref = self.visit(tree.children[0])
        aggregator = str(tree.children[1])
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

        relname = self.visit(tree.children[1].children[-1])

        # NOTE: again this is something where we might want to use context managers.
        self._bound_tuples[tuple_name] = self.rels[relname]

        # add index condition, if there is one.
        cond = ""
        if has_child(tree, "on_index"):
            cond = f" if {self.visit(tree.children[2])}"

        self._plan.children.append(
            PlanNode(f"for {tuple_name} ∈ {ram_relname}{cond}", [])
        )

        plan = self.visit(tree.children[-1])

        # we're exiting the scope where this tuple_name is valid.
        del self._bound_tuples[tuple_name]
        return plan

    def if_stmt(self, tree):
        assert self._plan is not None

        # TODO: We currently don't handle if statements that break
        if not has_child(tree, "BREAK"):
            if_cond = self.visit(tree.children[0])

            # add index condition, if there is one.
            index_cond = ""
            if has_child(tree, "on_index"):
                index_cond = f" using index {self.visit(tree.children[1])}"

            self._plan.children.append(PlanNode(f"if {if_cond}{index_cond}", []))

        return self.visit(tree.children[-1])

    def unpack_stmt(self, tree):
        assert self._plan is not None

        # TODO: Ideally we resolve ADT types here.
        iden = str(tree.children[0])
        tuple_element_ref = self.visit(tree.children[2])

        self._plan.children.append(PlanNode(f"{iden} := {tuple_element_ref}", []))

        return self.visit(tree.children[-1])

    def insert_stmt(self, tree):
        assert self._plan is not None

        tuple_expr = self.visit(tree.children[0])
        ram_relname = self.visit(tree.children[1])

        self._plan.text = f"{ram_relname} = {ram_relname} ∪ {{{tuple_expr} | "
        self._plan.trailer = "}"

        plan = self._plan

        # ... and we don't need this: other part of the non-local HACK.
        self._plan = None
        return plan

    def on_index(self, tree):
        return self.visit(tree.children[0])

    ### RAM conditions

    # TODO: Everything from ram_cond down. Don't forget to use self.rels for resolving tuple elements.
    def ram_cond(self, tree):
        def is_complex(tree: lark.tree.Tree):
            return len(tree.children) > 0

        def bracket_complex(tree: lark.tree.Tree | lark.lexer.Token):
            if isinstance(tree, lark.tree.Tree):
                if is_complex(tree):
                    return f"({self.visit(tree)})"
                else:
                    return self.visit(tree)
            else:
                return str(tree)

        return ", ".join(map(bracket_complex, tree.children))

    def or_cond(self, tree):
        return "; ".join(self.visit_children(tree))

    def and_cond(self, tree):
        return ", ".join(self.visit_children(tree))

    def not_cond(self, tree):
        return "!" + self.visit(tree.children[0])

    def in_cond(self, tree):
        return " ∈ ".join(self.visit_children(tree))

    def exists_cond(self, tree):
        return "∃" + str(tree.children[0]) + " ∈ " + self.visit(tree.children[1])

    def isempty_cond(self, tree):
        return self.visit(tree.children[0]) + " = ∅"

    def comparision(self, tree):
        return (
            self.visit(tree.children[0])
            + f" {str(tree.children[1])} "
            + self.visit(tree.children[2])
        )

    def bracketed_cond(self, tree):
        return f"({self.visit(tree.children[0])})"

    def tuple_expr(self, tree):
        return f"〈{','.join(self.visit_children(tree))}〉"

    def add_tuple_element(self, tree):
        return " + ".join(self.visit_children(tree))

    def sub_tuple_element(self, tree):
        return " - ".join(self.visit_children(tree))

    def undef(self, _):
        return "UNDEFINED"

    def tuple_element_literal(self, tree):
        return str(tree.children[0])

    def tuple_element_ref(self, tree):
        tuple_name = str(tree.children[0])

        colname = str(tree.children[1])
        if tuple_name in self._bound_tuples:
            # NOTE: We need this check because tuple_element_ref can also be used for indexing into types.
            colname = self._bound_tuples[tuple_name].attrs[int(colname)][0]

        return ".".join([tuple_name, colname])

    def functor_call(self, tree):
        return (
            self._safe_visit(tree.children[0])
            + "("
            + ",".join(map(self.visit, tree.children[1:]))
            + ")"
        )

    def userdef_functor(self, tree):
        return "@" + self.visit(tree.children[0])

    def bracketed_tuple_element(self, tree):
        return f"({self.visit(tree.children[0])})"

    def record_tuple_element(self, tree):
        return "[" + ",".join(self.visit_children(tree)) + "]"

    def ram_relname(self, tree):
        relname = self.visit(tree.children[-1])
        prefix = ""
        if len(tree.children) > 1:
            relkind = str(tree.children[0])

            if relkind == "@new_":
                prefix = "Δ[i+1]"
            elif relkind == "@delta_":
                prefix = "Δ[i]"
        return f"{prefix}{relname}"

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
