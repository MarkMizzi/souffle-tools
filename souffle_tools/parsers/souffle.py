import os

from lark import Lark
import lark.tree

from . import GRAMMARS_DIR

SOUFFLE_GRAMMAR_FILE = os.path.join(GRAMMARS_DIR, "souffle.lark")


class PreprocessorError(RuntimeError):
    ...


class SouffleError(RuntimeError):
    ...


_parser: Lark
with open(SOUFFLE_GRAMMAR_FILE, "r") as fl:
    _parser = Lark(fl, start="program")


def parse(fname: str, use_transformed: bool = False) -> lark.tree.Tree:
    """
    Parse a single source file, then return list of relevant entities in the file.
    """

    dirname, fname = os.path.dirname(fname), os.path.basename(fname)
    dirname = dirname or "."

    src: str
    if use_transformed:
        souffle = os.popen(
            f"sh -c 'cd {dirname} && souffle --show=transformed-datalog {fname}'",
            "r",
        )
        src = souffle.read()

        if (ecode := souffle.close()) == 0:
            raise SouffleError(
                f"Souffle process failed on source file {fname}: exit code {ecode}"
            )

    else:
        preprocessor = os.popen(f"sh -c 'cd {dirname} && cpp {fname} -o -'", "r")
        src = preprocessor.read()

        if (ecode := preprocessor.close()) == 0:
            raise PreprocessorError(
                f"C preprocessor failed on source file {fname}: exit code {ecode}"
            )

    return _parser.parse(src)
