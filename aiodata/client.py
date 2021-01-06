import asyncio
import aiohttp
import yarl
import ldbcache
import json
import collections


__all__ = ('Client',)


class Query:

    __slots__= ('_execute',)

    def __init__(self, execute):
        self._execute = execute

    def __await__(self, *args, **kwargs):
        return self._execute(*args, **kwargs).__await__()


class BulkQuery(Query):

    __slots__ = ('_attr', '_store')

    def __init__(self, attr, *args):
        super().__init__(*args)
        self._attr = attr
        self._store = []

    def _create(self):
        raise NotImplementedError()

    def _append(self, *args, **kwargs):
        value = self._create(*args, **kwargs)
        self._store.append(value)
        return self

    def __await__(self):
        return super().__await__(self._store)

    def __getattr__(self, attr):
        if not attr == self._attr:
            raise AttributeError(attr)
        return self._append


class BulkMerge(BulkQuery):

    __slots__ = ('_names',)

    def __init__(self, names, *args):
        super().__init__(*args)
        self._names = names

    def _create(self, *keys, **data):
        data.update(zip(self._names, keys))
        return data


class Table:

    """
    Table()

    Represents a database table.

    :var str name:
        The table's name.
    :var ~ldbcache.Entry fields:
        Contains fields against their names with the following details:

        .. csv-table::
            :header: "Attribute", "Type", "Description"
            :widths: auto

            "``name``",":class:`str`","Its name."
            "``main``",":class:`bool`","Whether this is a primary key."
            "``type``",":class:`str`","PostgreSQL type name."
            "``dims``",":class:`int`","Number of array dimensions."
            "``null``",":class:`bool`","Whether this is nullable."
            "``info``",":class:`str`","The attached databasae comment."
            "``refs``",":class:`tuple`\[:class:`str`]","The referenced table and field name or null for both."
    """

    __slots__ = ('_name', '_query', '_cache', '_fields')

    def __init__(self, name, query, cache, fields):

        self._name = name
        self._query = query
        self._cache = cache
        self._fields = fields

    @property
    def name(self):

        return self._name

    @property
    def fields(self):

        return self._fields

    def get(self, *keys):

        """
        Get entries at ``keys``.

        .. code-block:: py

            shibas = client.tables.pets.get('Dog', 'Shiba Inu')
        """

        return self._cache.select(keys)

    def __iter__(self):

        yield from self._cache.entries()

    def create(self, *keys, **data):

        """
        Insert new rows and return their respective entries.

        .. code-block:: py

            created = await client.tables.pets.create('Cat', 'Persian', 'Robert')

        .. code-block:: py

            created = await (
                client.tables.pets
                .create('Bird', 'Cockatiel', 'Tiko')
                .create('Bird', 'Conure', name = 'Ari', color = 255)
                .create('Hamster', breed = 'Syrian', name = 'Chops', groomed = True)
            )

        Uses an **awaitable** object leading to results.
        """

        execute = lambda data: self._query('POST', self._name, None, data)
        query = BulkMerge(self._cache.primary, 'create', execute)
        query.create(*keys, **data) # add this
        return query

    def update(self, *keys, **data):

        """
        Update entries at ``keys`` with ``data``.

        .. code-block:: py

            updated = await client.tables.pets.update('Lizard', 'Tegu', 'Rango', color = 65280)

        Uses an **awaitable** object leading to results.
        """

        execute = lambda: self._query('PATCH', self._name, keys, data)
        query = Query(execute)
        return query

    def delete(self, *keys):

        """
        Delete entries at ``keys``.

        .. code-block:: py

            deleted = await client.tables.pets.delete('Insect', 'Mosquito')

        Uses an **awaitable** object leading to results.
        """

        execute = lambda: self._query('DELETE', self._name, keys, None)
        query = Query(execute)
        return query

    def __repr__(self):

        return f'<{self.__class__.__name__}:{self._name}[{self._cache}]>'


class Error(Exception):

    """
    Raised when something goes wrong.

    :var ~ldbcache.Entry info:
        Contains all details sent by the server.
    """

    __slots__ = ('_info',)

    def __init__(self, data):
        super().__init__(json.dumps(data, indent = 2))
        self._indo = ldbcache.Entry(data)

    @property
    def info(self):
        return self._info


_ACTIONS = {
    'POST'  : ('create', 'create'),
    'PATCH' : ('modify', 'update'),
    'DELETE': ('delete', 'delete')
}


def _noop(*a, **k):
    pass


class Client:

    """
    Communicates with the module's server protocol.

    :param str url:
        Server url.
    :param str token:
        Authorization token.
    :param str query:
        Database query path.
    :param str state:
        Websocket connection path.
    :param func callback:
        Called upon events with:

        .. csv-table::
            :header: "Index","Type","Description"
            :widths: auto

            "``0``",":class:`str`","``create``, ``update`` or ``delete``."
            "``1``",":class:`str`","Table name."
            "``2``",":class:`tuple`\[:class:`Entry`]","Single entries or ``(old, new)`` pairs (``update`` only)."

    :var ~ldbcache.Entry tables:
        Contains :class:`.Table`\s against their names.

    .. note::
        Tables without primary keys will be generated, but:
        - Their cache won't be filled
        - Events related to them won't be dispatched.
    """

    def __init__(self,
                 url = 'http://localhost:4000',
                 token = None,
                 query = '/query',
                 state = '/state',
                 callback = None):

        self._url = yarl.URL(url)
        self._token = 'Bearer ' + token

        self._query = query
        self._state = state

        self._session = None
        self._websocket = None
        self._callback = callback or _noop

        self._tables = None

    @property
    def tables(self):

        return self._tables

    async def _request(self, method, path = '', json = None):

        url = self._url.with_path(path)

        response = await self._session.request(method, url, json = json)

        data = await response.json()

        if response.status < 400:
            return data if data else ()

        raise Error(data)

    async def _interact(self, method, table, keys = None, data = None):
        path = f'{self._query}/{table}'
        if keys:
            path = f'{path}/' + '/'.join(map(str, keys))
        data = await self._request(method, path, json = data)
        return map(ldbcache.Entry, data)

    async def _describe(self):
        while not self._session.closed:
            try:
                tables = await self._request('GET')
            except aiohttp.ClientError:
                await asyncio.sleep(1)
            else:
                break
        async def fill(name, cache):
            entries = await self._interact('GET', name)
            cache.create(None, entries)
        (result, tasks) = ({}, [])
        for (table, fields) in tables.items():
            (primary, general) = ([], [])
            for (field, info) in fields.items():
                if info['main']:
                    primary.append(field)
                info['name'] = field
                general.append(ldbcache.Entry(info))
            cache = ldbcache.AlikeBulkRowCache(primary)
            if primary:
                tasks.append(asyncio.create_task(fill(table, cache)))
            result[table] = Table(table, self._interact, cache, general)
        await asyncio.gather(*tasks)
        self._tables = ldbcache.Entry(result)

    def _handle(self, method, name, query, data):
        (attr, action) = _ACTIONS[method]
        cache = self._tables[name]._cache
        if not cache.primary: # nothing we can do
            return
        execute = getattr(cache, attr)
        result = execute(query, data)
        self._callback(action, name, result)

    async def _flow(self):
        async for message in self._websocket:
            payload = json.loads(message.data)
            self._handle(*payload)

    async def _connect(self):
        url = self._url.with_path(self._state)
        self._websocket = await self._session.ws_connect(url)

    async def _setup(self):
        headers = {}
        if (token := self._token):
            headers['Authorization'] = token
        self._session = aiohttp.ClientSession(headers = headers)

    async def start(self):

        """
        Create the session, fetch schema, fill cache, connect to websocket,
        listen for events.
        """

        await self._setup()
        await self._describe()
        await self._connect()
        asyncio.ensure_future(self._flow())

    async def stop(self):

        """
        Close the session and websocket connections.
        """

        await self._session.close()
        await self._websocket.close()
