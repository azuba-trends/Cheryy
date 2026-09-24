import zipfile
out = r"D:\Cheryy\dist\cheryy-ci-fixed-bundle.zip"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    z.write(r"D:\Cheryy\.github\workflows\build-windows.yml",
            arcname="build-windows.yml")
print(out)
