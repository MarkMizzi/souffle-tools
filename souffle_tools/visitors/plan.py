from collections.abc import Mapping
from typing import Dict, List

import lark.tree
import lark.lexer
from lark.visitors import Interpreter

from .utils import has_child
from .relations import Relation


class PyPlanVisitor(Interpreter):
    """
    Converts the RAM program from the compiler into a (non-functional) Python program.

    This gives us syntax highlighting and some other nice editor features for viewing the plan.
    """

    INDENT_GROUP = "   "

    def __init__(self, rels: Dict[str, Relation]):
        self.out = ""
        self.rels = rels
        self._bound_tuples = {}

    @classmethod
    def _stringify_plan(cls, plan: Dict, prefix: str = "") -> str:
        def stringify(c: Dict | str):
            if isinstance(c, Mapping):
                return cls._stringify_plan(c, prefix=cls.INDENT_GROUP + prefix)
            else:
                return cls.INDENT_GROUP + prefix + str(c)

        res: str
        if isinstance(plan["l"], str):
            res = prefix + plan["l"]
        else:
            res = "\n".join(map(prefix.__add__, plan["l"]))

        return res + "\n" + "\n".join(map(stringify, plan["c"]))

    def _safe_prepend(self, prefix: List[str] | str, ls: List[str] | str) -> List[str]:
        if isinstance(ls, str):
            ls = [ls]
        if isinstance(prefix, str):
            prefix = [prefix]
        return prefix + ls

    def _safe_visit(self, tree: lark.tree.Tree | lark.lexer.Token):
        if isinstance(tree, lark.tree.Tree):
            return self.visit(tree)
        else:
            return str(tree)

    def program(self, tree) -> str:
        def extract_stratum_number(subroutine_node: lark.tree.Tree) -> int:
            # bit of a HACK: depends on stratum names used by the souffle compiler.
            return int(str(subroutine_node.children[0]).split("_")[1])

        tree.children[1:-1] = sorted(tree.children[1:-1], key=extract_stratum_number)
        return "\n".join(
            map(self._stringify_plan, map(self.visit, tree.children[1:-1]))
        )

    def subroutine(self, tree) -> Dict:
        stratum_name = str(tree.children[0])
        return {
            "l": f"def {stratum_name}():",
            "c": list(map(self.visit, tree.children[1:])),
        }

    ### Subroutine statements

    def loop_stmt(self, tree) -> Dict:
        return {"l": f"while True:", "c": list(map(self.visit, tree.children[1:]))}

    def query_stmt(self, tree) -> Dict:
        return self.visit(tree.children[0])

    def debug_stmt(self, tree) -> Dict:
        # HACK: We need to do this because of the weird debug string format.
        res = {}
        exec(f"x = {str(tree.children[0])}", {}, res)
        debug_info = ['"""'] + res["x"].split("\n") + ['"""']

        plan = self.visit(tree.children[1])
        # NOTE: We don't need to check if plan is a str, this is guaranteed.
        plan["l"] = self._safe_prepend(debug_info, plan["l"])
        return plan

    def clear_stmt(self, tree) -> str:
        return f"{self.visit(tree.children[0])} = set()"

    def swap_stmt(self, tree) -> str:
        rel1, rel2 = self.visit_children(tree)
        return f"swap({rel1}, {rel2})"

    def exit_stmt(self, tree) -> str:
        return f"if {self.visit(tree.children[0])}: break"

    def io_stmt(self, tree) -> str:
        relname = self.visit(tree.children[0])
        io_options = dict(map(self.visit, tree.children[1:]))

        operation: str
        if io_options["operation"] == "input":
            operation = "input"
        elif io_options["operation"] == "output":
            operation = "output"
        else:
            raise RuntimeError(f"Unrecognized IO operation {io_options['operation']}")

        fname = ""
        if io_options.get("filename", relname).removesuffix(".dl") != relname:
            fname = f", filename={io_options['filename']}"

        delim = repr(io_options.get("delimiter", "\t"))

        return f"{operation}({relname}, delim={delim}{fname})"

    ### RAM statements

    def declare_stmt(self, tree) -> Dict:
        tuple_element_ref = self.visit(tree.children[0])
        aggregator = str(tree.children[1])
        tuple_name = str(tree.children[2])
        ram_relname = self.visit(tree.children[3])

        return {
            "l": f"{tuple_element_ref} = {aggregator}({tuple_name} for {tuple_name} in {ram_relname})",
            "c": [self.visit(tree.children[-1])],
        }

    def forloop(self, tree) -> Dict:
        tuple_name = str(tree.children[0])
        ram_relname = self.visit(tree.children[1])

        relname = self.visit(tree.children[1].children[-1])

        # NOTE: again this is something where we might want to use context managers.
        self._bound_tuples[tuple_name] = self.rels[relname]

        if has_child(tree, "on_index"):
            ram_relname = f"index_scan({ram_relname}, lambda {tuple_name}: {self.visit(tree.children[2])})"

        res = {
            "l": f"for {tuple_name} in {ram_relname}:",
            "c": [self.visit(tree.children[-1])],
        }

        # we're exiting the scope where this tuple_name is valid.
        del self._bound_tuples[tuple_name]
        return res

    def if_stmt(self, tree) -> Dict | str:
        if_cond = f"if {self.visit(tree.children[0])}"

        # add index condition, if there is one.
        if has_child(tree, "on_index"):
            if_cond += f" and index_cond(lambda : {self.visit(tree.children[1])})"

        if_cond += ":"

        plan = self.visit(tree.children[-1])

        if has_child(tree, "BREAK"):
            if_cond += " break"
            if isinstance(plan, str):
                return {"l": self._safe_prepend(if_cond, plan), "c": []}
            else:
                plan["l"] = self._safe_prepend(if_cond, plan["l"])
                return plan
        else:
            return {"l": if_cond, "c": [plan]}

    def unpack_stmt(self, tree) -> Dict:
        # TODO: Ideally we resolve ADT types here.
        iden = str(tree.children[0])
        tuple_element_ref = self.visit(tree.children[2])

        plan = self.visit(tree.children[-1])

        text = f"{iden} = {tuple_element_ref}"

        if isinstance(plan, str):
            return {"l": self._safe_prepend(text, plan), "c": []}
        else:
            plan["l"] = self._safe_prepend(text, plan["l"])
            return plan

    def insert_stmt(self, tree) -> str:
        tuple_expr = self.visit(tree.children[0])
        ram_relname = self.visit(tree.children[1])

        return f"{ram_relname}.add({tuple_expr})"

    def erase_stmt(self, tree) -> str:
        tuple_expr = self.visit(tree.children[0])
        ram_relname = self.visit(tree.children[1])

        return f"{ram_relname}.remove({tuple_expr})"

    def on_index(self, tree):
        return self.visit(tree.children[0])

    ### RAM conditions

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

        return " and ".join(map(bracket_complex, tree.children))

    def or_cond(self, tree):
        return " or ".join(self.visit_children(tree))

    def and_cond(self, tree):
        return " and ".join(self.visit_children(tree))

    def not_cond(self, tree):
        return "not " + self.visit(tree.children[0])

    def in_cond(self, tree):
        return " in ".join(self.visit_children(tree))

    def exists_cond(self, tree):
        return (
            "exists("
            + str(tree.children[0])
            + " in "
            + self.visit(tree.children[1])
            + ")"
        )

    def isempty_cond(self, tree):
        return self.visit(tree.children[0]) + " == set()"

    def comparision(self, tree):
        comparator = str(tree.children[1])
        if comparator == "=":
            comparator = "=="
        return (
            self.visit(tree.children[0])
            + f" {comparator} "
            + self.visit(tree.children[2])
        )

    def bracketed_cond(self, tree):
        return f"({self.visit(tree.children[0])})"

    def tuple_expr(self, tree):
        return f"({','.join(self.visit_children(tree))})"

    def add_tuple_element(self, tree):
        return " + ".join(self.visit_children(tree))

    def sub_tuple_element(self, tree):
        return " - ".join(self.visit_children(tree))

    def undef(self, _):
        return "_"

    def tuple_element_literal(self, tree):
        return str(tree.children[0])

    def tuple_element_ref(self, tree):
        tuple_name = str(tree.children[0])

        colname = str(tree.children[1])
        if tuple_name in self._bound_tuples:
            # NOTE: We need this check because tuple_element_ref can also be used for indexing into types.
            colname = self._bound_tuples[tuple_name].attrs[int(colname)][0]
        else:
            colname = f"_{colname}"

        return ".".join([tuple_name, colname])

    def functor_call(self, tree):
        return (
            self._safe_visit(tree.children[0])
            + "("
            + ",".join(map(self.visit, tree.children[1:]))
            + ")"
        )

    def userdef_functor(self, tree):
        return "__functor_" + self.visit(tree.children[0])

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
                prefix = "__new_"
            elif relkind == "@delta_":
                prefix = "__delta_"
            elif relkind == "@delete_":
                prefix = "__delete_"
            elif relkind == "@reject_":
                prefix = "__reject_"
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
        return (str(tree.children[0]), self.visit(tree.children[1]))

    def string(self, tree):
        return str(tree.children[0])

    def number(self, tree):
        return int(tree.children[0])

    def true(self, _):
        return True

    def false(self, _):
        return False

    def null(self, _):
        return None
