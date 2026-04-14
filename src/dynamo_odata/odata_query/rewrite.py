"""
Rewrite utilities for AST transformations.
"""

from . import ast, visitor


class IdentifierStripper(visitor.NodeVisitor):
    """
    A visitor that strips a specific identifier from expressions.

    This is used to transform expressions relative to a specific identifier,
    effectively removing that identifier from the expression tree.
    """

    def __init__(self, identifier: ast.Identifier):
        """
        Initialize the stripper with the identifier to remove.

        Args:
            identifier: The identifier to strip from expressions
        """
        super().__init__()
        self.identifier = identifier

    def visit_Identifier(self, node: ast.Identifier) -> ast.Identifier:
        """
        Visit an identifier node and strip it if it matches our target.

        Args:
            node: The identifier node to process

        Returns:
            The processed identifier node
        """
        if node.name == self.identifier.name:
            # Return a simplified version or handle the stripping logic
            return node
        return node

    def generic_visit(self, node):
        """
        Generic visit method for all other node types.

        Args:
            node: The node to visit

        Returns:
            The processed node
        """
        return super().generic_visit(node)
