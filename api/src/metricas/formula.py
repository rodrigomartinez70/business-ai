"""
Evaluador de fórmulas SEGURO para KPIs particulares.

Parsea la fórmula con `ast` y solo permite: números, nombres (= métricas del
catálogo), aritmética (+ - * / ** %), unario ±, comparaciones, y un set chico de
funciones (min/max/abs/round). NADA de `eval`, atributos, llamadas arbitrarias,
ni acceso a Python. División por cero → 0.0 (evita romper un dashboard).
"""

import ast
import operator

_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
}
_FUNCS = {"min": min, "max": max, "abs": abs, "round": round}


class FormulaError(ValueError):
    pass


def nombres_referenciados(expr: str) -> set[str]:
    """Nombres de métricas usados en la fórmula (excluye funciones permitidas)."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise FormulaError(f"sintaxis inválida: {e}") from e
    nombres = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    return nombres - set(_FUNCS)


def evaluar(expr: str, valores: dict[str, float]) -> float:
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise FormulaError(f"sintaxis inválida: {e}") from e
    return float(_ev(tree.body, valores))


def _ev(node, valores: dict[str, float]) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise FormulaError("constante no permitida")
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in valores:
            raise FormulaError(f"métrica desconocida: {node.id}")
        return float(valores[node.id])
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        v = _ev(node.operand, valores)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp):
        op = _BINOPS.get(type(node.op))
        if op is None:
            raise FormulaError("operador no permitido")
        a, b = _ev(node.left, valores), _ev(node.right, valores)
        if isinstance(node.op, (ast.Div, ast.Mod)) and b == 0:
            return 0.0
        return op(a, b)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise FormulaError("función no permitida")
        args = [_ev(a, valores) for a in node.args]
        return _FUNCS[node.func.id](*args)
    raise FormulaError("expresión no permitida")
