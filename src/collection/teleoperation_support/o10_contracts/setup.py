"""Package metadata for omnihand_o10_contracts.

This is the single code owner (ARCHITECTURE invariant A11) of the O10 logical
Side and the 10 active-joint names, indices and per-side limits, plus the pure
validated joint target/feedback/error/time value objects shared by retargeting,
control and providers. It depends only on the Python standard library and numpy.
"""

from setuptools import find_packages, setup

package_name = 'omnihand_o10_contracts'

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
    install_requires=['setuptools', 'numpy'],
    zip_safe=True,
    maintainer='Dexhit',
    maintainer_email='noreply@dexhit.local',
    description=(
        'Pure O10 shared semantics and value objects: logical Side, the 10 '
        'active-joint names/indices/per-side limits and validated joint '
        'target/feedback/error/time value objects.'
    ),
    license='TODO',
    tests_require=['pytest'],
)
