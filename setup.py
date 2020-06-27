from setuptools import setup, find_packages

setup(
    name='madbg',
    version='1.0.0',
    packages=find_packages(exclude=('tests',)),
    # TODO: this still installs successfully on windows
    classifiers=['Operating System :: POSIX :: Linux'],  # TODO: we probably support more than just linux
    install_requires=['click', 'ipython>=7.6.0', 'prompt_toolkit'],
    # TODO: merge ipython patch to python2 branch, allowing support of python 2?
    entry_points=dict(
        console_scripts=['madbg=madbg.__main__']
    )
    # TODO: copy some nice setup.py and upload to pypi
)
