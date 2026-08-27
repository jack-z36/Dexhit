from setuptools import find_packages, setup

package_name = "omnihand_o10_hardware_adapter"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "omnihand_o10_hardware_provider = omnihand_o10_hardware_adapter.node:main",
        ],
    },
)
