"""Production-only composition package metadata."""

from pathlib import Path

from setuptools import find_packages, setup


package_name = "rokoko_omnihand_bringup"
package_root = Path(__file__).resolve().parent
launch_files = [
    path.relative_to(package_root).as_posix()
    for path in sorted((package_root / "launch").glob("*.launch.py"))
]
config_files = [
    path.relative_to(package_root).as_posix()
    for path in sorted((package_root / "config").glob("*.yaml"))
]

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", launch_files),
        ("share/" + package_name + "/config", config_files),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Dexhit",
    maintainer_email="noreply@dexhit.local",
    description="Production-only Rokoko to OmniHand O10 composition.",
    license="TODO",
    tests_require=["pytest"],
)
