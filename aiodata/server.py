
"""
Launch a proxy for tranforming `/paths/like/these` to PostgREST filters.

Usage:
    aiodata -h | --help
    aiodata <file> [--host=<str>] [--port=<int>] [--query=<str>] [--state=<str>]
    aiodata [--db-uri=<uri>] [--pr-uri=<uri>] [--host=<str>] [--port=<int>] [--schema=<str>] [--secret=<str>] [--query=<str>] [--state=<str>]

Options:
    -h --help           Show this screen.
    file                Path to the `.conf` file for PostgREST.
    --db-uri=<uri>      Uri to the PostgreSQL database.                         [default: postgres://admin@localhost/postgres]
    --pr-uri=<uri>      Uri to the PostgREST server.                            [default: http://localhost:3000]
    --host=<str>        Host to launch the proxy at.                            [default: localhost]
    --port=<int>        Port to launch the proxy at.                            [default: 4000]
    --schema=<str>      The exposed schema to describe.                         [default: api]
    --secret=<str>      Authenticates websocket tokens (claims dont matter).
    --query=<str>       Routing path to expose queries at.                      [default: /query]
    --state=<str>       Routing path to expose websockets at if applicable.     [default: /state]

Queries are proxy-adjusted requests whose paths get trasformed to filters.

For example, `/table/val1/val2` turns into `/table?clm1=eq.val1&clm2=eq.val2`.

- There is no way to specify the returned columns.
- All responses use the `Prefer: return=representation` header.
- Binary values are not supported. Covert to base64 in the databse.

Websocket connections are iniated through `/state`.
Authorization is only enforced if `secret` is present. Claims are irrelevant.
Json data is sent upon any successful POST, PATCH or DELETE.

The payload itself is a 4-item array:
1: Name of the request method.
2: Name of the affected table.
3: Query used for this operation, eg {"clm1": "val1", "clm2": "val2"}.
4: The entries returned from the PostgREST response.

Send a `SIGUSR1` signal to reload the schema upon changes.
"""

import asyncio
import asyncpg
import aiohttp
import aiohttp.web
import yarl
import os
import aiofiles
import collections
import itertools
import jwt
import signal
import json
import warnings
import sys
import docopt
import configparser
import io


__all__ = ()


def connect(uri):
    return asyncpg.create_pool(
        host = uri.host,
        port = uri.port,
        user = uri.user,
        password = uri.password,
        database = uri.parts[1]
    )


_NOTIFY = {'POST', 'PATCH', 'DELETE'}


_HDRS_PASS = {'Authorization', 'Range', 'Content-Type'}
_HDRS_SKIP = {'Content-Type'}


_anon = object()


class Server:

    """
    Main means of launching the server proxy.

    :param asyncpg.pool.Pool pool:
        The connection pool.
    :param str origin:
        The PostgreSQL database uri.
    :param str target:
        The address to connect to.
    :param str schema:
        The schema exposed by PostgREST.
    """

    __slots__ = ('_pool', '_session', '_origin', '_schema', '_script',
                 '_details', '_primaries', '_secret', '_websockets', '_ready')

    path = '/{steps:.+}'

    def __init__(self, pool, origin, schema, secret = None):

        self._pool = pool
        self._session = None

        self._origin = origin
        self._schema = schema

        self._script = None
        self._details = None
        self._primaries = None

        self._secret = secret
        self._websockets = collections.defaultdict(list)

        self._ready = asyncio.Event()

    @property
    def details(self):
        return self._details

    @property
    def ready(self):
        return self._ready

    def _resolve_path(self, path):

        """
        Get query and tables.
        """

        (table, *values) = path.split('/')
        names = self._primaries.get(table, ())
        query = tuple(zip(names, values))
        return (table, query)

    def _resolve_query(self, query):

        """
        Get PostgREST filter.
        """

        return {name: f'eq.{value}' for (name, value) in query}

    def _auth(self, headers):
        token = headers.get('Authorization')
        if self._secret and token:
            token = token.split(' ')[-1] # - Bearer
            claims = jwt.decode(token, self._secret)
            return claims['role']
        return _anon

    async def query(self, request):

        """
        Handle requests to querying the database.
        """

        await self._ready.wait()

        method = request.method

        headers = request.headers.copy()
        for key in tuple(headers.keys()):
            if key in _HDRS_PASS:
                continue
            del headers[key]

        headers['Prefer'] = 'return=representation'

        path = request.match_info['steps']
        (table, query) = self._resolve_path(path)
        params = self._resolve_query(query)
        uri = self._origin.with_path(table)
        data = request.content

        response = await self._session.request(
            method,
            uri,
            params = params,
            headers = headers,
            data = data
        )

        if 200 <= response.status <= 201 and method in _NOTIFY:
            entries = await response.json()
            try:
                (names, values) = zip(*query)
            except ValueError:
                values = ()
            payload = json.dumps((method, table, values, entries))
            apply = lambda websocket: websocket.send_str(payload)
            try:
                role = self._auth(headers)
            except jwt.InvalidSignatureError:
                warnings.warn('Secret could not validate accepted token.')
            else:
                websockets = self._websockets[role]
                await asyncio.gather(*map(apply, websockets))
            data = json.dumps(entries).encode()
        else:
            data = response.content

        response = aiohttp.web.Response(
            body = data,
            headers = response.headers,
            status = response.status,
        )

        response.enable_compression()
        response.enable_chunked_encoding()

        return response

    async def state(self, request, id = None):

        """
        Handle requests for connecting to the database.
        """

        try:
            role = self._auth(request.headers)
        except jwt.InvalidSignatureError:
            raise aiohttp.web.HTTPUnauthorized(reason = 'Invalid token.')
        websockets = self._websockets[role]

        websocket = aiohttp.web.WebSocketResponse(heartbeat = 30)
        await websocket.prepare(request)

        websockets.append(websocket)
        try:
            async for message in websocket:
                pass # receiving does nothing
        finally:
            websockets.remove(websocket)

        return websocket

    async def describe(self):

        """
        Create the schema description.
        """

        self._ready.clear()

        entries = await self._pool.fetch(self._script)

        details = collections.defaultdict(dict)
        primaries = collections.defaultdict(list)
        for entry in map(dict, entries):
            table = entry.pop('table')
            field = entry.pop('field')
            details[table][field] = entry
            if entry['main']:
                primaries[table].append(field)

        self._details = dict(details)
        self._primaries = dict(primaries)

        self._ready.set()

    async def _load(self, name = 'schema.psql'):

        """
        Get the description script.
        """

        path = os.path.realpath(__file__)
        directory = os.path.dirname(path)
        path = os.path.join(directory, name)
        async with aiofiles.open(path) as file:
            template = await file.read()
            self._script = template.format(self._schema)

    async def _setup(self):

        self._session = aiohttp.ClientSession(skip_auto_headers = _HDRS_SKIP)

    async def start(self):

        """
        Start the client.
        """

        await self._load()
        await self._setup()
        await self.describe()

    async def stop(self):

        """
        Stop the client.
        """

        await self._session.close()

        apply = lambda websocket: websocket.close()
        websockets = itertools.chain.from_iterable(self._websockets.values())
        await asyncio.gather(*map(apply, websockets))
        self._websockets.clear()


async def make(pool,
               uri ,
               schema = 'api',
               secret = None,
               query = '/query',
               state = '/state'):

    routes = aiohttp.web.RouteTableDef()

    server = Server(pool, uri, schema, secret = secret)

    path = query + server.path
    for verb in ('GET', 'POST', 'PATCH', 'DELETE'):
        routes.route(verb, path)(server.query)

    async def handle(request):
        await server.ready.wait()
        return aiohttp.web.json_response(server.details)
    routes.route('GET', '/')(handle)

    routes.route('GET', state)(server.state)

    return (routes, server)


async def main(app, db_uri, pr_uri, host, port, **options):

    """
    Start the proxy.

    :param str db_uri:
        URL for the PostgreSQL database.
    :param str pr_uri:
        URL for the PostgREST server.
    :param str host:
        Host to launch the proxy at.
    :param int port:
        Port to launch the proxy at.
    :param str schema:
        The exposed schema.
    :param str secret:
        Used for authenticating websocket tokens and use their ``role`` claim.
    :param str query:
        The path to expose queries at.
    :param str state:
        The path to expose websockets at if applicable.
    """

    loop = asyncio.get_event_loop()

    db_uri = yarl.URL(db_uri)
    pool = await connect(db_uri)

    pr_uri = yarl.URL(pr_uri)
    (routes, server) = await make(pool, pr_uri, **options)
    app.router.add_routes(routes)

    reload = lambda: asyncio.ensure_future(server.describe())

    loop.add_signal_handler(signal.SIGUSR1, reload)

    await server.start()

    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, host, port)
    await site.start()

    try:
        await loop.create_future()
    except asyncio.CancelledError:
        pass

    await server.stop()
    await site.stop()
    await runner.cleanup()


def serve(env_prefix = 'AIODT_'):

    """
    Console functionality.
    """

    args = docopt.docopt(__doc__, argv = sys.argv[1:])

    def geta(key):
        try:
            conkey = key.lstrip('-').replace('-', '_').upper()
            return os.environ[env_prefix + conkey]
        except KeyError:
            pass
        return args[key]

    pr_uri = yarl.URL(geta('--pr-uri'))

    if (path := args['<file>']):
        config = configparser.ConfigParser()
        with open(path) as file:
            data = file.read()
        head = '_'
        data = f'[{head}]\n{data}'
        config.read_string(data)
        config = config[head]
        def getf(key, default = None, /):
            try:
                value = config[key]
            except KeyError:
                return default
            return value.strip('"')
        db_uri = getf('db-uri')
        schema = getf('db-schema')
        secret = getf('jwt-secret')
        if (host := getf('server-host', None)):
            pr_uri = pr_uri.with_host(host)
        if (port := getf('server-port', None)):
            pr_uri = pr_uri.with_port(int(port))
    else:
        db_uri = geta('--db-uri')
        schema = geta('--schema')
        secret = geta('--secret')

    host = geta('--host')
    port = geta('--port')
    port = int(port)

    query = geta('--query')
    state = geta('--state')

    loop = asyncio.get_event_loop()
    app = aiohttp.web.Application()

    task = loop.create_task(
        main(
            app, db_uri, pr_uri, host, port,
            schema = schema, secret = secret,
            query = query, state = state
        )
    )

    try:
        loop.run_until_complete(task)
    except KeyboardInterrupt:
        pass

    task.cancel()

    try:
        loop.run_until_complete(task)
    except asyncio.CancelledError:
        pass
