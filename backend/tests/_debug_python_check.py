from cheryy.security import _DESTRUCTIVE_PY, Policy, DestructiveActionInterceptor

ic = DestructiveActionInterceptor(Policy())
for src in ("os.remove('foo')", "shutil.rmtree('foo')", "pathlib.Path('x').unlink()", "send2trash('foo')"):
    print(repr(src), '-> match=', bool(_DESTRUCTIVE_PY.search(src)))
    try:
        ic.assert_python_safe(src)
        print('   RAISED nothing')
    except Exception as e:
        print('   RAISED:', type(e).__name__, e)