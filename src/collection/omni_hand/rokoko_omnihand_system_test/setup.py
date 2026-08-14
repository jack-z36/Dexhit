"""Package metadata for the software O10 provider system-test package."""

from setuptools import find_packages, setup

package_name = 'rokoko_omnihand_system_test'

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
    description='Deterministic in-process O10 software provider and system tests.',
    license='TODO',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'software_o10_provider = '
            'rokoko_omnihand_system_test.provider:main',
        ],
    },
)