"""Math solver tool — 3-tier: AST eval -> SymPy -> LLM fallback."""

import ast
import logging
import operator
from typing import Any

from trio.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Safe operators for AST evaluation
_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(expr: str) -> float | None:
    """Evaluate a math expression safely using AST."""
    try:
        tree = ast.parse(expr, mode="eval")
        return _eval_node(tree.body)
    except Exception:
        return None


def _eval_node(node):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("Non-numeric constant")
    elif isinstance(node, ast.BinOp):
        op = _SAFE_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        return op(left, right)
    elif isinstance(node, ast.UnaryOp):
        op = _SAFE_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported unary op: {type(node.op).__name__}")
        return op(_eval_node(node.operand))
    else:
        raise ValueError(f"Unsupported node: {type(node).__name__}")


def _sympy_solve(expr: str) -> str | None:
    """Try to solve using SymPy."""
    try:
        import sympy
        result = sympy.sympify(expr)
        simplified = sympy.simplify(result)
        return str(simplified)
    except Exception:
        return None


class MathSolverTool(BaseTool):
    """Solve mathematical expressions and equations."""

    @property
    def name(self) -> str:
        return "math_solver"

    @property
    def description(self) -> str:
        return (
            "Solve mathematical expressions and equations. Handles arithmetic, "
            "algebra, calculus, and symbolic math. Use this for precise calculations."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "The math expression or equation to solve",
                },
            },
            "required": ["expression"],
        }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        expr = params.get("expression", "").strip()
        if not expr:
            return ToolResult(output="Error: No expression provided", success=False)

        # Tier 1: Safe AST evaluation (basic arithmetic)
        result = _safe_eval(expr)
        if result is not None:
            return ToolResult(
                output=f"{expr} = {result}",
                metadata={"method": "ast_eval", "result": result},
            )

        # Tier 2: SymPy (symbolic math)
        sympy_result = _sympy_solve(expr)
        if sympy_result is not None:
            return ToolResult(
                output=f"{expr} = {sympy_result}",
                metadata={"method": "sympy", "result": sympy_result},
            )

        # Tier 3: Return for LLM fallback
        return ToolResult(
            output=f"Could not compute '{expr}' directly. Please solve this step by step.",
            metadata={"method": "llm_fallback"},
        )
