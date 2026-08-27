"""Package metadata for the cross-package architecture gates."""

from setuptools import find_packages, setup


package_name = "rokoko_omnihand_architecture_test"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name, ["REVIEW_CHECKLIST.md"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Dexhit",
    maintainer_email="noreply@dexhit.local",
    description="Blocking cross-package architecture and ownership gates.",
    license="TODO",
    tests_require=["pytest"],
)
