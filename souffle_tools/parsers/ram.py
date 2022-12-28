import os

from lark import Lark
import lark.tree

from . import GRAMMARS_DIR
from .souffle import SouffleError


RAM_GRAMMAR_FILE = os.path.join(GRAMMARS_DIR, "ram.lark")


_parser: Lark
with open(RAM_GRAMMAR_FILE, "r") as fl:
    _parser = Lark(fl, start="program")


def parse(fname: str, use_transformed: bool = True) -> lark.tree.Tree:
    """
    Parse a single source file, then return list of relevant entities in the file.
    """

    dirname, fname = os.path.dirname(fname), os.path.basename(fname)
    dirname = dirname or "."

    ram_version = "transformed" if use_transformed else "initial"
    souffle = os.popen(
        f"sh -c 'cd {dirname} && souffle --show={ram_version}-ram {fname}'",
        "r",
    )
    src = souffle.read()

    if ecode := souffle.close():
        raise SouffleError(
            f"Souffle process failed on source file {fname}: exit code {ecode}"
        )

    return _parser.parse(src)
