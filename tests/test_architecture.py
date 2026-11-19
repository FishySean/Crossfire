"""依赖方向的自动检查：扫描 import 语句，内层不许依赖外层。

  domain       → 只能依赖标准库和 domain 自己
  application  → 只能依赖标准库、domain、application
  adapters     → 可以依赖任何东西
  pipeline.py  → 兼容门面，负责组装，可以依赖 adapters，第 4 步删除
  _wiring.py   → 临时组装点，只有入口（scripts/、web/）可以 import 它

application/use_cases 另有一条更严的规则：不许有文件、线程、JSON、系统时钟的代码。

函数体里的延迟 import 也会被扫到。
"""

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "crossfire"

LAYERS = {
    "domain": ("crossfire.domain",),
    "application": ("crossfire.domain", "crossfire.application"),
}
USE_CASE_FILES = sorted((PACKAGE / "application" / "use_cases").rglob("*.py"))


def module_name(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def imports_of(path: Path) -> list[str]:
    """文件里所有 import 的绝对模块名，相对 import 会被解析成绝对名。"""
    package = module_name(path) if path.name == "__init__.py" else module_name(path).rpartition(".")[0]
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")[: len(package.split(".")) - node.level + 1]
                found.append(".".join([*base, node.module] if node.module else base))
            else:
                found.append(node.module or "")
    return found


def violations(paths, allowed_prefixes):
    bad = []
    for path in paths:
        for module in imports_of(path):
            if module.split(".")[0] in sys.stdlib_module_names:
                continue
            if any(module == prefix or module.startswith(prefix + ".") for prefix in allowed_prefixes):
                continue
            bad.append(f"{path.relative_to(ROOT)} imports {module}")
    return bad


@pytest.mark.parametrize("layer", sorted(LAYERS))
def test_inner_layers_depend_only_inward(layer):
    paths = sorted((PACKAGE / layer).rglob("*.py"))
    assert paths, f"crossfire/{layer}/ 下没有文件，检查是不是空转了"
    assert violations(paths, LAYERS[layer]) == []


def test_use_case_depends_only_on_domain_and_application():
    assert violations(USE_CASE_FILES, LAYERS["application"]) == []


def test_nothing_inside_the_package_imports_the_temporary_wiring():
    offenders = [
        str(path.relative_to(ROOT))
        for path in sorted(PACKAGE.rglob("*.py"))
        if path.name != "_wiring.py" and "crossfire._wiring" in imports_of(path)
    ]
    assert offenders == []


# use case 只编排端口。读写文件、开线程、序列化 JSON、读系统时钟都是适配器的事。
SIDE_EFFECT_MODULES = {
    "asyncio",
    "concurrent",
    "datetime",
    "io",
    "json",
    "multiprocessing",
    "os",
    "pathlib",
    "shutil",
    "socket",
    "subprocess",
    "tempfile",
    "threading",
    "time",
}
SIDE_EFFECT_BUILTINS = {"open", "print", "input"}


def side_effects(path: Path) -> list[str]:
    found = [
        f"imports {module}" for module in imports_of(path) if module.split(".")[0] in SIDE_EFFECT_MODULES
    ]
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in SIDE_EFFECT_BUILTINS:
            found.append(f"calls {node.func.id}()")
    return found


def test_use_cases_contain_no_file_thread_or_json_code():
    paths = sorted((PACKAGE / "application" / "use_cases").rglob("*.py"))
    assert paths
    assert {str(path.relative_to(ROOT)): side_effects(path) for path in paths} == {
        str(path.relative_to(ROOT)): [] for path in paths
    }


def test_the_side_effect_checker_catches_a_violation(tmp_path, monkeypatch):
    """对照组：证明上面的空列表不是因为检查器什么都没认出来。"""
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    bad = tmp_path / "bad.py"
    bad.write_text("import json\nfrom threading import Thread\n\ndef f():\n    open('x')\n", encoding="utf-8")
    assert side_effects(bad) == ["imports json", "imports threading", "calls open()"]


def test_the_checker_catches_a_violation(tmp_path, monkeypatch):
    """对照组：证明上面的空列表不是因为扫描器什么都没扫到。"""
    fake_root = tmp_path
    layer = fake_root / "crossfire" / "domain"
    layer.mkdir(parents=True)
    (layer / "bad.py").write_text("import anthropic\nfrom ..adapters.steel import CACHE_ROOT\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", fake_root)
    found = violations([layer / "bad.py"], LAYERS["domain"])
    assert found == [
        "crossfire/domain/bad.py imports anthropic",
        "crossfire/domain/bad.py imports crossfire.adapters.steel",
    ]
