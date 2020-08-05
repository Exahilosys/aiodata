import setuptools

with open('README.rst') as file:

    readme = file.read()

name = 'aiodata'

version = '2.1.1'

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
        'asyncpg',
        'aiohttp',
        'yarl',
        'aiofiles',
        'pyjwt',
        'docopt',
        'vessel'
    ],
    entry_points = {
        'console_scripts': [
            f'{name}={name}.server:serve'
        ]
    }
)
