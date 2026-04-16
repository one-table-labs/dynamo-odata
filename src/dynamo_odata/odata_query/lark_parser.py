from __future__ import annotations

from lark import Lark, Token, Transformer, UnexpectedInput

from . import ast, exceptions

_GRAMMAR = r"""
?start: expr

?expr: or_expr

?or_expr: or_expr OR and_expr   -> bool_op
        | and_expr

?and_expr: and_expr AND not_expr -> bool_op
         | not_expr

?not_expr: NOT not_expr          -> unary_not
         | compare_expr

?compare_expr: arith_expr EXISTS       -> postfix_func
             | arith_expr NOT_EXISTS   -> postfix_func
             | arith_expr EQ arith_expr -> compare
             | arith_expr NE arith_expr -> compare
             | arith_expr LT arith_expr -> compare
             | arith_expr LE arith_expr -> compare
             | arith_expr GT arith_expr -> compare
             | arith_expr GE arith_expr -> compare
             | arith_expr IN list_expr  -> compare
             | arith_expr BETWEEN list_expr -> compare
             | arith_expr

?arith_expr: arith_expr ADD term -> bin_op
           | arith_expr SUB term -> bin_op
           | term

?term: term MUL factor -> bin_op
     | term DIV factor -> bin_op
     | term MOD factor -> bin_op
     | factor

?factor: SUB factor -> unary_minus
       | atom

?atom: literal
     | function_call
     | identifier
     | "(" expr ")"

function_call: identifier "(" [arg_list] ")"
arg_list: expr ("," expr)*

list_expr: "(" expr "," ")"               -> single_list
         | "(" expr ("," expr)+ ")"       -> multi_list

identifier: ODATA_IDENTIFIER

?literal: NULL
        | BOOLEAN
        | DATETIME
        | DATE
        | TIME
        | DURATION
        | DECIMAL
        | INTEGER
        | GUID
        | STRING

EXISTS.3: /exists(?![\w.])/i
NOT_EXISTS.3: /not_exists(?![\w.])/i
BETWEEN.3: /between(?![\w.])/i
AND.3: /and(?![\w.])/i
OR.3: /or(?![\w.])/i
NOT.3: /not(?![\w.])/i
EQ.3: /eq(?![\w.])/i
NE.3: /ne(?![\w.])/i
LT.3: /lt(?![\w.])/i
LE.3: /le(?![\w.])/i
GT.3: /gt(?![\w.])/i
GE.3: /ge(?![\w.])/i
IN.3: /in(?![\w.])/i
ADD.3: /add(?![\w.])/i
SUB.3: /sub(?![\w.])/i
MUL.3: /mul(?![\w.])/i
DIV.3: /div(?![\w.])/i
MOD.3: /mod(?![\w.])/i
NULL.3: /null(?![\w.])/i
BOOLEAN.3: /true(?![\w.])/i | /false(?![\w.])/i
DURATION.3: /duration'[+-]?P(?:\d+D)?(?:T(?:\d+H)?(?:\d+M)?(?:\d+(?:\.\d+)?S)?)?'/i
DATETIME.3: /[1-9]\d{3}-(?:0\d|1[0-2])-(?:[0-2]\d|3[01])T(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d{1,12})?)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)?/
DATE.3: /[1-9]\d{3}-(?:0\d|1[0-2])-(?:[0-2]\d|3[01])/
TIME.3: /(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d{1,12})?)?/
DECIMAL.3: /[+-]?\d+(?:(?:\.\d+)(?:e[-+]?\d+)|(?:\.\d+)|(?:e[-+]?\d+))/i
INTEGER.3: /[+-]?\d+/
GUID.3: /[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}/i
STRING.3: /'(?:[^']|'')*'/
ODATA_IDENTIFIER.1: /[_a-zA-Z](?:\.?\w){0,127}/

%import common.WS
%ignore WS
"""


class ODataTransformer(Transformer):
    def identifier(self, items):
        token = str(items[0])
        *namespace, name = token.split(".")
        return ast.Identifier(name, tuple(namespace))

    def NULL(self, _token):
        return ast.Null()

    def BOOLEAN(self, token):
        return ast.Boolean(str(token).lower())

    def INTEGER(self, token):
        return ast.Integer(str(token))

    def DECIMAL(self, token):
        return ast.Float(str(token))

    def STRING(self, token):
        value = str(token)[1:-1].replace("''", "'")
        return ast.String(value)

    def GUID(self, token):
        return ast.GUID(str(token))

    def DATE(self, token):
        return ast.Date(str(token))

    def TIME(self, token):
        return ast.Time(str(token))

    def DATETIME(self, token):
        return ast.DateTime(str(token))

    def DURATION(self, token):
        value = str(token)
        value = value[len("duration") + 1 : -1]
        return ast.Duration(value.upper())

    def EQ(self, _token):
        return ast.Eq()

    def NE(self, _token):
        return ast.NotEq()

    def LT(self, _token):
        return ast.Lt()

    def LE(self, _token):
        return ast.LtE()

    def GT(self, _token):
        return ast.Gt()

    def GE(self, _token):
        return ast.GtE()

    def IN(self, _token):
        return ast.In()

    def BETWEEN(self, _token):
        return ast.Between()

    def EXISTS(self, _token):
        return ast.Exists()

    def NOT_EXISTS(self, _token):
        return ast.Not_Exists()

    def AND(self, _token):
        return ast.And()

    def OR(self, _token):
        return ast.Or()

    def ADD(self, _token):
        return ast.Add()

    def SUB(self, _token):
        return ast.Sub()

    def MUL(self, _token):
        return ast.Mult()

    def DIV(self, _token):
        return ast.Div()

    def MOD(self, _token):
        return ast.Mod()

    def compare(self, items):
        return ast.Compare(items[1], items[0], items[2])

    def bool_op(self, items):
        return ast.BoolOp(items[1], items[0], items[2])

    def bin_op(self, items):
        return ast.BinOp(items[1], items[0], items[2])

    def unary_not(self, items):
        return ast.UnaryOp(ast.Not(), items[-1])

    def unary_minus(self, items):
        return ast.UnaryOp(ast.USub(), items[-1])

    def postfix_func(self, items):
        return ast.Function(items[1], items[0])

    def single_list(self, items):
        return ast.List([items[0]])

    def multi_list(self, items):
        return ast.List(items)

    def arg_list(self, items):
        return items

    def function_call(self, items):
        func = items[0]
        args = items[1] if len(items) > 1 else []
        if not isinstance(args, list):
            args = [args]
        return self._function_call(func, args)

    def _function_call(self, func: ast.Identifier, args: list[ast._Node]):
        func_name = func.name
        try:
            n_args_exp = ODATA_FUNCTIONS[func_name]
        except KeyError as exc:
            raise exceptions.UnknownFunctionException(func_name) from exc

        n_args_given = len(args)
        if isinstance(n_args_exp, int) and n_args_given != n_args_exp:
            raise exceptions.ArgumentCountException(func_name, n_args_exp, n_args_exp, n_args_given)

        if isinstance(n_args_exp, tuple) and (n_args_given < n_args_exp[0] or n_args_given > n_args_exp[1]):
            raise exceptions.ArgumentCountException(func_name, n_args_exp[0], n_args_exp[1], n_args_given)

        return ast.Call(func, args)


ODATA_FUNCTIONS = {
    "concat": 2,
    "contains": 2,
    "endswith": 2,
    "indexof": 2,
    "length": 1,
    "startswith": 2,
    "substring": (2, 3),
    "matchesPattern": 2,
    "tolower": 1,
    "toupper": 1,
    "trim": 1,
    "year": 1,
    "month": 1,
    "day": 1,
    "hour": 1,
    "minute": 1,
    "second": 1,
    "fractionalseconds": 1,
    "totalseconds": 1,
    "date": 1,
    "time": 1,
    "totaloffsetminutes": 1,
    "mindatetime": 0,
    "maxdatetime": 0,
    "now": 0,
    "round": 1,
    "floor": 1,
    "ceiling": 1,
    "geo.distance": 1,
    "geo.length": 1,
    "geo.intersects": 2,
    "hassubset": 2,
    "hassubsequence": 2,
}


_PARSER = Lark(_GRAMMAR, parser="lalr", maybe_placeholders=False)
_TRANSFORMER = ODataTransformer()


def parse_odata(filter_str: str) -> ast._Node:
    try:
        return _TRANSFORMER.transform(_PARSER.parse(filter_str))
    except UnexpectedInput as exc:
        token = None
        if getattr(exc, "token", None) is not None:
            token = Token(str(exc.token.type), str(exc.token))
        raise exceptions.ParsingException(token, token is None) from exc


class ODataLexer:
    def tokenize(self, filter_str: str) -> str:
        return filter_str


class ODataParser:
    def parse(self, token_stream: str) -> ast._Node:
        return parse_odata(token_stream)
