"""依赖方向的自动检查：扫描 import 语句，内层不许依赖外层。

  domain       → 只能依赖标准库和 domain 自己
  application  → 只能依赖标准库、domain、application
  adapters     → 可以依赖任何东西
  composition  → 组合根，crossfire/ 里唯一可以 import adapters 的模块
  入口         → web/、scripts/、app.py、crossfire/cli.py 只能 import composition、config、domain
                 和 application 的公开类型（use_cases、events、records）

另外：只有 crossfire/config.py 可以读 .env 和环境变量（load_dotenv、dotenv、os.environ、os.getenv）。

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


ENTRY_POINTS = [
    *sorted((ROOT / "web").rglob("*.py")),
    *sorted((ROOT / "scripts").rglob("*.py")),
    ROOT / "app.py",
    PACKAGE / "cli.py",
]
ENTRY_POINT_ALLOWED = (
    "crossfire.composition",
    "crossfire.config",
    "crossfire.domain",
    "crossfire.application.use_cases",
    "crossfire.application.events",
    "crossfire.application.records",
    "web",
)


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def is_under(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def test_only_the_composition_root_imports_adapters():
    offenders = [
        f"{relative(path)} imports {module}"
        for path in sorted(PACKAGE.rglob("*.py"))
        if not path.is_relative_to(PACKAGE / "adapters")
        and path != PACKAGE / "composition.py"
        for module in imports_of(path)
        if is_under(module, "crossfire.adapters")
    ]
    assert offenders == []


def entry_point_violations(paths):
    return [
        f"{relative(path)} imports {module}"
        for path in paths
        if path.exists()
        for module in imports_of(path)
        if (is_under(module, "crossfire") or is_under(module, "web"))
        and not any(is_under(module, allowed) for allowed in ENTRY_POINT_ALLOWED)
    ]


def test_entry_points_import_only_composition_config_domain_and_public_application_types():
    assert entry_point_violations(ENTRY_POINTS) == []


def env_reads(path: Path) -> list[str]:
    """import dotenv、调 load_dotenv/dotenv_values、碰 os.environ/os.getenv/environ。"""
    found = [f"imports {module}" for module in imports_of(path) if is_under(module, "dotenv")]
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv", "environb", "putenv"}:
            found.append(f"uses .{node.attr}")
        elif isinstance(node, ast.Name) and node.id in {"environ", "getenv", "load_dotenv", "dotenv_values"}:
            found.append(f"uses {node.id}")
        elif isinstance(node, ast.ImportFrom) and node.module == "os":
            found.extend(f"imports os.{alias.name}" for alias in node.names if alias.name in {"environ", "getenv"})
    return found


SOURCE_FILES = [
    *sorted(PACKAGE.rglob("*.py")),
    *sorted((ROOT / "web").rglob("*.py")),
    *sorted((ROOT / "scripts").rglob("*.py")),
    ROOT / "app.py",
]


def test_only_config_reads_the_environment():
    offenders = {
        relative(path): env_reads(path)
        for path in SOURCE_FILES
        if path != PACKAGE / "config.py" and env_reads(path)
    }
    assert offenders == {}


def test_the_env_checker_catches_a_violation(tmp_path, monkeypatch):
    """对照组：几种常见写法都要认得出来。"""
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    bad = tmp_path / "bad.py"
    bad.write_text(
        "import os\nfrom os import environ\nfrom dotenv import load_dotenv\n"
        "load_dotenv()\nos.environ.get('K')\nos.getenv('K')\n",
        encoding="utf-8",
    )
    assert sorted(env_reads(bad)) == sorted(
        ["imports dotenv", "imports os.environ", "uses load_dotenv", "uses .environ", "uses .getenv"]
    )


def test_the_entry_point_checker_catches_a_violation(tmp_path, monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    bad = tmp_path / "server.py"
    bad.write_text(
        "from crossfire.adapters.storage import JsonRunRepository\nfrom crossfire.application.ports import EventSink\n"
        "from crossfire.composition import build_verifier\nimport fastapi\n",
        encoding="utf-8",
    )
    assert entry_point_violations([bad]) == [
        "server.py imports crossfire.adapters.storage",
        "server.py imports crossfire.application.ports",
    ]


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


# 主程序不依赖 torch：流水线在没装训练组的环境里必须能跑。
# adapters/nli/ 里将来可以有加载模型的适配器；encoding.py 只做字符串拼接，禁止碰它们。
TORCH_BANNED_ROOTS = ("torch", "transformers")


def _imports_torch_or_transformers(module: str) -> bool:
    top = module.split(".")[0]
    return top in TORCH_BANNED_ROOTS


def _nli_file_may_import_torch(path: Path) -> bool:
    nli = PACKAGE / "adapters" / "nli"
    if not path.is_relative_to(nli):
        return False
    return path.name not in {"encoding.py", "__init__.py"}


def torch_import_offenders() -> list[str]:
    bad: list[str] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if _nli_file_may_import_torch(path):
            continue
        for module in imports_of(path):
            if _imports_torch_or_transformers(module):
                bad.append(f"{relative(path)} imports {module}")
    return bad


def test_crossfire_does_not_import_torch_or_transformers_outside_nli_model_adapter():
    assert torch_import_offenders() == []


def test_nli_encoding_must_not_import_torch(tmp_path, monkeypatch):
    """对照组：encoding.py 即使在 nli/ 下也不能 import torch。"""
    monkeypatch.setattr(sys.modules[__name__], "PACKAGE", tmp_path / "crossfire")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    nli = tmp_path / "crossfire" / "adapters" / "nli"
    nli.mkdir(parents=True)
    (nli / "encoding.py").write_text("import torch\n", encoding="utf-8")
    (nli / "model.py").write_text("import torch\n", encoding="utf-8")
    offenders = torch_import_offenders()
    assert "crossfire/adapters/nli/encoding.py imports torch" in offenders
    assert "crossfire/adapters/nli/model.py imports torch" not in offenders
