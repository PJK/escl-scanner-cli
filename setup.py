from setuptools import setup

setup(
    # https://pypi.org/project/scanner-cli/ already taken
    name="escl-scanner-cli",
    version='0.1',
    py_modules=['scanner'],
    install_requires=[
        'requests',
        'xmltodict',
        'zeroconf',
    ],
    entry_points={
        'console_scripts': [
            'escl-scan = scanner:main',
        ],
    },
)