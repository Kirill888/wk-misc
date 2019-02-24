from setuptools import setup, find_packages

setup(
    name='dc-tools',
    version='0.1',
    license='Apache License 2.0',
    # url='https://github.com/opendatacube/benchmark-rio-s3',
    packages=find_packages(),
    # include_package_data=True,
    author='Kirill Kouzoubov',
    author_email='kirill.kouzoubov@ga.gov.au',
    description='TODO',
    python_requires='>=3.5',
    install_requires=['datacube',
                      'click',
                      ],
    tests_require=['pytest'],
    extras_require=dict(),
    entry_points={
        'console_scripts': [
            'dc-tools = dc_tools.app:cli',
        ],
    }
)
