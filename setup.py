import setuptools

with open('README.rst') as file:

    readme = file.read()

name = 'aiodata'

version = '3.0.0'

author = 'Exahilosys'

url = f'https://github.com/{author}/{name}'

setuptools.setup(
    name = name,
    version = version,
    author = author,
    url = url,
    packages = setuptools.find_packages(),
    license = 'MIT',
    description = 'PostgREST proxy and client.',
    long_description = readme,
    package_data = {
        '': ['*.psql']
    },
    install_requires = [
        'asyncpg<1.0',
        'aiohttp<4.0',
        'yarl<2.0',
        'aiofiles<1.0',
        'pyjwt<3.0',
        'docopt<1.0',
        'ldbcache<1.0'
    ],
    entry_points = {
        'console_scripts': [
            f'{name}={name}.server:serve'
        ]
    }
)
