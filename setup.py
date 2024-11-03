from setuptools import setup

with open('README.md') as f:
    long_description = f.read()

setup(
    # https://pypi.org/project/scanner-cli/ already taken
    name="escl-scanner-cli",
    version='0.1.1',
    description='Control eSCL network scanners using a CLI utility',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/PJK/escl-scanner-cli',
    author='https://github.com/zegman, Pavel Kalvoda',
    author_email='me@pavelkalvoda.com',
    license='Apache',
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
