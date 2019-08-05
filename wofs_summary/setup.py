from setuptools import setup

setup(
    name='kk_wofs_summary',
    version='0.0.1',

    author='Kirill Kouzoubov',
    author_email='kirill.kouzoubov@ga.gov.au',

    description='',
    long_description='',

    license='Apache License 2.0',

    tests_require=['pytest'],
    install_requires=[
        'distributed',
        'click',
        'datacube'
    ],

    packages=['kk.wofs_summary'],
    zip_safe=False,
)
