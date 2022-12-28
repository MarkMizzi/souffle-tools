from typing import Generator
from lark.lexer import Token
from lark.tree import Tree


def children_by_name(tree: Tree, name: str) -> Generator[Token | Tree, None, None]:

    for child in tree.children:
        if getattr(child, "data", None) == name:
            yield child


def has_child(tree: Tree, name: str) -> bool:
    return any(getattr(child, "data", None) == name for child in tree.children)
