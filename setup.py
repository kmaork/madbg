from setuptools import setup, find_packages

setup(
    name='madbg',
    version='1.0.0',
    packages=find_packages(exclude=('tests',)),
    # TODO: this still installs successfully on windows
    classifiers=['Operating System :: POSIX :: Linux'],  # TODO: we probably support more than just linux
    install_requires=['click',
                      # 'ipython>=7.6.0',
                      'IPython @ git+ssh://git@github.com/ipython/ipython.git@cc9da29abf59e877e7a9aff2558ddc15604c324b#egg=IPython',
                      'prompt_toolkit'],
    # TODO: merge ipython patch to python2 branch, allowing support of python 2?
    entry_points=dict(
        console_scripts=['madbg=madbg.__main__:cli']
    )
    # TODO: copy some nice setup.py and upload to pypi
)
