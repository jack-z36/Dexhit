"""Package metadata for the Rokoko hand receiver."""

from setuptools import find_packages, setup


package_name = "rokoko_hand_receiver"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools", "lz4"],
    zip_safe=True,
    maintainer="Dexhit",
    maintainer_email="noreply@dexhit.local",
    description=(
        "Strict Rokoko JSON v3 UDP receiver publishing per-side RawHandFrame "
        "messages."
    ),
    license="TODO",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "rokoko_hand_receiver_node = rokoko_hand_receiver.node:main",
        ],
    },
)
