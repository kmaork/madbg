from setuptools import setup, find_packages

setup(
    name='madbg',
    version='1.1.0',
    packages=find_packages(exclude=('tests',)),
    classifiers=['Operating System :: POSIX :: Linux'],
    install_requires=['click',
                      'IPython>=7.17.0',
                      'prompt_toolkit',
                      'hypno>=0.1.3'],
    entry_points=dict(
        console_scripts=['madbg=madbg.__main__:cli']
    )
)
