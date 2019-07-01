from setuptools import setup, find_packages

setup(
    name='madbg',
    version='1.0.0',
    packages=find_packages(exclude=('tests',)),
    classifiers=['Operating System :: POSIX :: Linux'],  # TODO: we probably support more than just linux
    install_requires=['click', 'ipython', 'futures ; python_version<"3"', 'prompt_toolkit'],
    entry_points=dict(
        console_scripts=['madbg=madbg.__main__']
    )
)
