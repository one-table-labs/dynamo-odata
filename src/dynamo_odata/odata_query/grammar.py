"""Compatibility parser module backed by Lark."""

from .lark_parser import ODataLexer, ODataParser, parse_odata

__all__ = ["ODataLexer", "ODataParser", "parse_odata"]
