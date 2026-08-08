"""Scripts and pages are the only code with no test that runs them.

`bank_data_response.py` shipped calling `build_provider()` when the function
had required an argument for some time. Everything imported, every unit test
passed, and the failure appeared the first time a human ran the command --
after the table had already printed, which made it look like a data problem.

This checks, without running anything, that every call in scripts/ and pages/
to a function imported from src/ actually matches that function's signature.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CALLER_DIRS = ("scripts", "pages")


def caller_files() -> list[Path]:
    out: list[Path] = []
    for folder in CALLER_DIRS:
        out.extend(sorted((ROOT / folder).glob("*.py")))
    return out


def test_there_are_callers_to_check():
    """A silent zero-file scan would make every assertion below vacuous."""
    assert len(caller_files()) >= 10


def imported_from_src(tree: ast.Module) -> dict[str, tuple[str, str]]:
    """{local name: (module, attribute)} for `from src.x import y [as z]`."""
    found: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("src."):
            for alias in node.names:
                if alias.name != "*":
                    found[alias.asname or alias.name] = (node.module, alias.name)
    return found


def resolve(module_name: str, attribute: str):
    try:
        module = importlib.import_module(module_name)
    except Exception:  # noqa: BLE001 - a missing optional dep is not this test's business
        return None
    return getattr(module, attribute, None)


def signature_problems(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = imported_from_src(tree)
    problems: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        local = node.func.id
        if local not in imports:
            continue
        target = resolve(*imports[local])
        if target is None or not (inspect.isfunction(target) or inspect.isclass(target)):
            continue
        try:
            sig = inspect.signature(target)
        except (TypeError, ValueError):
            continue

        # We know how many arguments are passed and their keyword names, not
        # their values, so bind placeholders. *args / **kwargs at the call site
        # make the count unknowable — skip those rather than guess.
        if any(isinstance(a, ast.Starred) for a in node.args):
            continue
        if any(k.arg is None for k in node.keywords):
            continue

        positional = [object()] * len(node.args)
        keywords = {k.arg: object() for k in node.keywords}
        try:
            sig.bind(*positional, **keywords)
        except TypeError as exc:
            problems.append(
                f"{path.relative_to(ROOT)}:{node.lineno}: {local}(...) does not "
                f"match {local}{sig} -- {exc}"
            )
    return problems


@pytest.mark.parametrize("path", caller_files(), ids=lambda p: p.name)
def test_calls_into_src_match_their_signatures(path: Path):
    problems = signature_problems(path)
    assert not problems, "\n".join(problems)


def test_the_check_would_have_caught_the_real_bug(tmp_path):
    """Guard the guard: if this stopped detecting anything it would pass
    silently forever."""
    bad = tmp_path / "bad_script.py"
    bad.write_text(
        "from src.llm.provider import build_provider\n"
        "provider = build_provider()\n",
        encoding="utf-8",
    )
    tree = ast.parse(bad.read_text(encoding="utf-8"), filename=str(bad))
    imports = imported_from_src(tree)
    assert "build_provider" in imports

    target = resolve(*imports["build_provider"])
    assert target is not None
    with pytest.raises(TypeError):
        inspect.signature(target).bind()


def test_every_script_and_page_parses():
    """A syntax error in a script is invisible to the rest of the suite."""
    for path in caller_files():
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
