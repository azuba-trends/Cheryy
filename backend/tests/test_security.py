"""Security engine tests — the most important tests in the whole project.

These prove that destructive operations CANNOT slip through, regardless of:
  - whether they're issued via a tool
  - whether they look like path-based, shell, or python API calls
  - the user's granted permissions
"""
from __future__ import annotations

import pytest

from cheryy.security import (
    ActionPolicyEngine,
    Decision,
    DestructiveActionInterceptor,
    PermissionManager,
    Policy,
    Risk,
    classify_shell_command,
    is_protected_path,
    normalise_path,
)


def test_classify_shell_command_blocks_destructive():
    assert classify_shell_command("Remove-Item C:\\Users\\me\\file.txt") is Risk.DESTRUCTIVE
    assert classify_shell_command("del /f file.txt") is Risk.DESTRUCTIVE
    assert classify_shell_command("rm -rf /") is Risk.DESTRUCTIVE
    assert classify_shell_command("rd /s /q folder") is Risk.DESTRUCTIVE
    assert classify_shell_command("format c:") is Risk.DESTRUCTIVE
    assert classify_shell_command("diskpart /clean") is Risk.DESTRUCTIVE
    assert classify_shell_command("shutil.rmtree('foo')") is Risk.DESTRUCTIVE


def test_classify_shell_command_allows_safe():
    assert classify_shell_command("Get-Process") is Risk.SAFE
    assert classify_shell_command("dir") is Risk.SAFE
    assert classify_shell_command("Get-ChildItem") is Risk.SAFE
    assert classify_shell_command("echo hello") is Risk.SAFE


def test_classify_path_action_blocks_delete():
    pm = PermissionManager()
    pm.policy.auto_approve_elevated = True
    engine = ActionPolicyEngine(pm)
    # These verbs produce DESTRUCTIVE risk.
    for verb in ("delete", "unlink", "rm", "rmdir", "shred", "remove"):
        risk = engine.classify_path_action(verb, "C:\\Users\\me\\test.txt")
        assert risk is Risk.DESTRUCTIVE


def test_interceptor_refuses_path_delete():
    ic = DestructiveActionInterceptor(Policy())
    with pytest.raises(PermissionError):
        ic.assert_path_safe("delete", "C:\\Users\\me\\test.txt")
    with pytest.raises(PermissionError):
        ic.assert_path_safe("unlink", "C:\\test.txt")
    # move/rename/copy are allowed.
    ic.assert_path_safe("move", "C:\\Users\\me\\test.txt")
    ic.assert_path_safe("rename", "C:\\Users\\me\\test.txt")


def test_interceptor_refuses_shell_destructive():
    ic = DestructiveActionInterceptor(Policy())
    with pytest.raises(PermissionError):
        ic.assert_shell_safe("del C:\\Users\\me\\test.txt")
    with pytest.raises(PermissionError):
        ic.assert_shell_safe("Remove-Item foo")


def test_interceptor_blocks_destructive_python():
    ic = DestructiveActionInterceptor(Policy())
    for src in (
        "os.remove('foo')",
        "shutil.rmtree('foo')",
        "pathlib.Path('x').unlink()",
        "send2trash('foo')",
    ):
        with pytest.raises(PermissionError):
            ic.assert_python_safe(src)


def test_decide_denies_destructive_even_if_granted():
    pm = PermissionManager()
    pm.grant("fs", "fs.delete")
    engine = ActionPolicyEngine(pm)
    # Even with an explicit grant, DESTRUCTIVE must be denied.
    decision = engine.decide("fs", "fs.delete", risk=Risk.DESTRUCTIVE)
    assert decision is Decision.DENY


def test_decide_requires_user_for_elevated_by_default():
    pm = PermissionManager()
    engine = ActionPolicyEngine(pm)
    assert engine.decide("shell", "shell.run", risk=Risk.ELEVATED) is Decision.REQUIRE_USER
    # With auto-approve, it's still ALLOW for elevated.
    pm.policy.auto_approve_elevated = True
    assert engine.decide("shell", "shell.run", risk=Risk.ELEVATED) is Decision.ALLOW


def test_decide_allows_safe():
    pm = PermissionManager()
    engine = ActionPolicyEngine(pm)
    assert engine.decide("fs", "filesystem.list", risk=Risk.SAFE) is Decision.ALLOW


def test_is_protected_path_blocks_system_paths():
    win = os.environ.get("SystemRoot", r"C:\Windows")
    assert is_protected_path(win + r"\System32\config\\SAM")
    assert is_protected_path(r"C:\$Recycle.Bin\file")
    # A user path is NOT protected.
    assert not is_protected_path(str(normalise_path("C:\\Users\\me\\Documents\\file.txt")))


import os  # noqa: E402  (used above)