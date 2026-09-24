import zipfile
out = r"D:\Cheryy\dist\cheryy-ci-bundle.zip"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    z.write(r"D:\Cheryy\.github\workflows\build-windows.yml",
            arcname="build-windows.yml")
    z.write(r"D:\Cheryy\installer\prepare_icons.py",
            arcname="prepare_icons.py")
print(out)
