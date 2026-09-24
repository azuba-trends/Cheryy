from pathlib import Path
d = Path(r"D:\Cheryy\dist\test_icons")
exp = {
    '32x32.png':     b'\x89PNG',
    '128x128.png':   b'\x89PNG',
    '128x128@2x.png':b'\x89PNG',
    'icon.ico':      b'\x00\x00\x01\x00',
    'icon.icns':     b'icns',
}
ok = True
for name, want in exp.items():
    p = d/name
    head = p.read_bytes()[:len(want)]
    same = head == want
    ok &= same
    status = 'OK' if same else 'MISMATCH'
    print(f'  {name:18}  {p.stat().st_size:>7} bytes  magic={head!r}  {status}')
print('OVERALL:', 'PASS' if ok else 'FAIL')
from PIL import Image
for n in ('32x32.png','128x128.png','128x128@2x.png'):
    im = Image.open(d/n)
    print(f'  {n} dims: {im.size}')
