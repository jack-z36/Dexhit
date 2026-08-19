"""Package metadata for the local Launchpad control plane."""

from pathlib import Path

from setuptools import find_packages, setup


package_name = "rokoko_omnihand_launchpad"
package_root = Path(__file__).resolve().parent
data_files = [
    ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
    ("share/" + package_name, ["package.xml"]),
]
frontend_dist = package_root / "web" / "dist"
if frontend_dist.is_dir():
    for path in sorted(frontend_dist.rglob("*")):
        if path.is_file():
            relative_parent = path.parent.relative_to(frontend_dist).as_posix()
            install_dir = "share/" + package_name + "/web"
            if relative_parent != ".":
                install_dir += "/" + relative_parent
            data_files.append((install_dir, [path.relative_to(package_root).as_posix()]))

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=data_files,
    install_requires=["setuptools", "fastapi", "uvicorn", "PyYAML"],
    zip_safe=True,
    maintainer="Dexhit",
    maintainer_email="noreply@dexhit.local",
    description="Local FastAPI control-plane skeleton for Rokoko and OmniHand O10.",
    license="TODO",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "rokoko_omnihand_launchpad = "
            "rokoko_omnihand_launchpad.main:main",
        ],
    },
)
