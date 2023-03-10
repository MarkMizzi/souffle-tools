from typing import List

import typer

from .visitors.plan import PyPlanVisitor
from .visitors.ram_simplify import RAMSimplifier
from .visitors.indexes import IndexVisitor
from .visitors.relations import RelationVisitor
from .parsers import ram, souffle

app = typer.Typer()


@app.command()
def parse_files(files: List[str], use_transformed: bool = False):
    """
    Parse Souffle programs passed as args, and then throw away the result.

    Useful for debugging the grammars.
    """
    for fname in files:
        souffle.parse(fname, use_transformed=use_transformed)


@app.command()
def relations(file: str):
    """
    List relations in the input program.
    """

    souffle_ast = souffle.parse(file, use_transformed=True)

    relvisitor = RelationVisitor()
    relvisitor.visit(souffle_ast)

    for rel in relvisitor.rels.values():
        print(rel)


@app.command()
def indexes(file: str):
    """
    List indexes generated by the compiler for the Souffle program passed as arg.

    The list is conservative (i.e. some indexes may not be included)
    """

    souffle_ast = souffle.parse(file, use_transformed=True)
    ram_ast = ram.parse(file)

    relvisitor = RelationVisitor()
    relvisitor.visit(souffle_ast)

    index_visitor = IndexVisitor(rels=relvisitor.rels)
    index_visitor.visit(ram_ast)

    print("WARNING: This list is conservative. Some indexes may not be included.")
    for relname, indexes in index_visitor.indexes.items():
        print(relname)
        for idx in indexes:
            print(idx.index_type_str())


@app.command()
def explain(file: str):
    """
    Generate a (non-functional) Python-like program from the compiler's RAM representation.
    """

    souffle_ast = souffle.parse(file, use_transformed=True)
    ram_ast = ram.parse(file)

    relvisitor = RelationVisitor()
    relvisitor.visit(souffle_ast)

    simplifier = RAMSimplifier()
    simplified_ram_ast = simplifier.transform(ram_ast)

    plan_visitor = PyPlanVisitor(rels=relvisitor.rels)
    print(plan_visitor.visit(simplified_ram_ast))


app()
