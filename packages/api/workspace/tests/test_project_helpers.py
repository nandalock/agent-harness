"""Project identity and membership checks shared by the workspace controller."""
import os
import tempfile
from pathlib import Path

from agent_platform_api_workspace.service import (
    WorkspaceService,
    _canonical_project_path,
    _project_label,
)


def _service() -> WorkspaceService:
    return WorkspaceService(None, None, None)


def test_canonical_project_path_normalizes_spellings():
    """同一个目录的多种写法归一到同一个 key（唯一性是**路径字符串相等**）"""
    canon = _canonical_project_path
    assert canon("D:/jk/Nexus/proj") == "D:/jk/Nexus/proj"
    assert canon("D:\\jk\\Nexus\\proj\\") == "D:/jk/Nexus/proj"      # 反斜杠 + 尾斜杠
    assert canon("d:/jk/Nexus/proj") == "D:/jk/Nexus/proj"           # 盘符大小写不敏感
    assert canon("D:/jk/Nexus/./proj") == "D:/jk/Nexus/proj"         # 当前目录
    assert canon("D:/jk/Nexus/sub/../proj") == "D:/jk/Nexus/proj"    # 词法展开 ..
    assert canon("D:/jk//Nexus///proj") == "D:/jk/Nexus/proj"        # 重复分隔符
    assert canon("C:/") == "C:/"                                     # 根：尾斜杠要留着


def test_project_label_is_last_segment():
    """项目显示名 = 末段；根目录没有末段 → 回落成整串（不能显示空标题）"""
    assert _project_label("D:/jk/Nexus/proj") == "proj"
    assert _project_label("C:/") == "C:/"
    assert _project_label("//server/share") == "share"


def test_project_membership_needs_ledger_and_live_dir():
    """项目归属 = **账目** + 读时二次校验，两者缺一不可。

    账目是唯一的成员来源：没登记过（或登记已被移除）→ 未分组，绝不会因为「那个
    目录恰好还在」又自己冒出来 —— 这正是「移除项目」能生效、且旧会话不复活的原因。
    账目在但目录没了 → 也读作未分组（而不是让会话从列表里消失）。
    """
    service = _service()
    with tempfile.TemporaryDirectory() as tmp:
        alive = os.path.join(tmp, "alive")
        os.makedirs(alive)
        canonical = _canonical_project_path(alive)
        row = {"id": 7, "canonical_path": canonical, "title": "alive", "sort_order": 10.0}
        ledger = {"s1": row}
        alive_path = Path(alive)

        # 账目在 + cwd 对得上 + 目录还在 → 有归属
        got = service._project_for("s1", alive, alive_path, ledger)
        assert got is not None and got.id == 7 and got.key == canonical
        assert got.label == "alive"

        # 账目里没有这个会话（没登记过 / 登记被移除）→ 未分组
        assert service._project_for("s2", alive, alive_path, ledger) is None

        # 目录已被删（账目还在）→ 未分组
        gone = os.path.join(tmp, "gone")
        gone_ledger = {"s1": {**row, "canonical_path": _canonical_project_path(gone)}}
        assert service._project_for("s1", gone, Path(gone), gone_ledger) is None
        # 目录解析不出来（调用方给 None）同样未分组
        assert service._project_for("s1", alive, None, ledger) is None

        # 账目在，但会话现在的 cwd 不是这个目录（目录被改名 / 换了工作区）→ 未分组
        assert service._project_for("s1", os.path.join(tmp, "moved"), alive_path, ledger) is None

        # 没有 cwd（自动工作区 <root>/<session_id>）→ 未分组：目录名是会话 id
        assert service._project_for("s1", None, alive_path, ledger) is None
        assert service._project_for("s1", "", alive_path, ledger) is None


def test_project_identity_is_path_not_label():
    """两个不同目录同名 → 两个项目（按路径区分）；同一个目录只算一个"""
    a = _canonical_project_path("D:/jk/Nexus/test1")
    b = _canonical_project_path("D:/jk/Else/test1")
    assert a != b                                   # key 不同 → 两个项目
    assert _project_label(a) == _project_label(b) == "test1"   # 但显示名可以重名
