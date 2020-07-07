from setuptools import setup, find_packages

setup(
    name='madbg',
    version='1.0.0',
    packages=find_packages(exclude=('tests',)),
    classifiers=['Operating System :: POSIX :: Linux'],
    install_requires=['click',
                      'IPython @ git+ssh://git@github.com/ipython/ipython.git#egg=IPython',
                      'prompt_toolkit'],
    entry_points=dict(
        console_scripts=['madbg=madbg.__main__:cli']
    )
)
