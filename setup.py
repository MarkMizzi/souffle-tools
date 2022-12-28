from setuptools import find_packages, setup

setup(
    name="souffle-tools",
    description="Utilities for the Souffle programming language.",
    version="1.0.0",
    packages=find_packages(),
    install_requires=["lark", "typer"],
)
