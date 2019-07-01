from setuptools import setup, find_packages

setup(
    name='madbg',
    packages=find_packages(exclude=('tests',)),
    classifiers=['Operating System :: POSIX :: Linux'],
    install_requires=['click', 'ipython', 'futures ; python_version<"3"', 'prompt_toolkit'],
    entry_points=dict(
        console_scripts=['madbg=madbg.__main__']
    )
)
