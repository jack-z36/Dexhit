"""Package metadata for the OmniHand O10 control node."""

from setuptools import find_packages, setup

package_name = 'omnihand_o10_control'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        (
            'share/ament_index/resource_index/packages',
            ['resource/' + package_name],
        ),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Dexhit',
    maintainer_email='noreply@dexhit.local',
    description='Per-side arm-free, fault-latched hard-slew control for OmniHand O10.',
    license='TODO',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'o10_control_node = omnihand_o10_control.node:main',
        ],
    },
)