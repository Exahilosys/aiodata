Quickstart
==========

Jump `here`_ if you know how to make a PostREST database.

Setup
-----

Create roles and tables (`guide <http://postgrest.org/en/v6.0/tutorials/tut0.html>`_):

.. code-block:: postgresql

  CREATE ROLE anon;
  CREATE ROLE auth;

  CREATE SCHEMA api;

  GRANT USAGE ON SCHEMA api TO anon;
  GRANT USAGE ON SCHEMA api TO auth;

  CREATE TABLE api.pets
  (
    type TEXT,
    breed TEXT,
    name TEXT,
    color INT,
    groomed BOOL DEFAULT FALSE,
    PRIMARY KEY(type, breed, name)
  );

  GRANT SELECT ON api.pets TO anon; -- missing token means we can only read
  GRANT ALL    ON api.pets TO auth; -- having token means we can do anything


Make a ``postgrest.conf`` file (`guide <http://postgrest.org/en/v6.0/configuration.html>`_):

.. code-block::

  db-uri = "postgres://auth@localhost/postgres"
  db-schema = "api"
  db-anon-role = "anon"
  jwt-secret = "superdupersecret" # change this!

Launch ``PostgREST``:

.. code-block:: bash

  $ postgrest postgrest.conf # http://localhost:3000

Launch ``aiodata``:

.. code-block:: bash

  $ aiodata postgrest.conf # http://localhost:4000

Using `<https://jwt.io>`_ with ``superdupersecret`` for the ``auth`` role, we get:

.. code-block:: py

    token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoiYXV0aCJ9.jOVzPENev84OP1c0E1uVT1YvmBZPXQUD7pz_vlAAZx4'

.. _here:

Usage
-----

.. code-block:: py

  import asyncio
  import aiodata

  loop = asyncio.get_event_loop()

  # called upon events
  def callback(action, table, entries):
    print('Action :', action)
    print('Table  :', table)
    print('Entries:', entries)

  # connects to http://localhost:4000 using the above token
  client = aiodata.Client(token = token, callback = callback)

  async def main():
    # fill up database and listen to events
    await client.start()

    # we got some new fish and a dog
    created = await (
      client.tables.pets
      .create('Fish', 'Koi', 'Aqui')
      .create('Fish', 'Koi', 'Luna')
      .create('Dog', 'Shiba Inu', name = 'Munch', color = 16766362)
    )
    # map object, can't index
    (aqui, luna, munch) = created
    # obviously not
    print('Is munch groomed?', munch.groomed)
    # might as well groom all of our dogs
    updated = await client.tables.pets.update('Dog', groomed = True)
    # oh no! we knocked the Koi tank over
    deleted = await client.tables.pets.delete('Fish', 'Koi')
    # wait to see all events
    await asyncio.sleep(1)
    # get all our fish (not async)
    fish = client.tables.pets.get('Fish')
    # close all connections
    await client.stop()

  loop.run_until_complete(main())

Use tools like :mod:`wrapio`\'s :class:`~.wrapio.Track` to manage events:

.. code-block:: py

  import asyncio
  import aiodata
  import wrapio

  loop = asyncio.get_event_loop()

  # signal use of asyncio
  track = wrapio.Track(loop = loop)

  def callback(action, table, entries):
    # name of the event
    name = f'{action}_{table}'
    # pass to our track
    return track.invoke(name, entries)

  # connects to http://localhost:4000 using the above token
  client = aiodata.Client(callback = callback, token = token)

  @track.call
  async def update_pets(entries):
    for (old, new) in entries:
      # [...]

  @track.call
  async def create_pets(entries):
    for entry in entries:
      # [...]

  @track.call
  async def delete_pets(entries):
    for entry in entries:
      # [...]

  async def main():
    # [...]

  loop.run_until_complete(main())

**And that's it!** You can now access and manage your database remotely with ease.

Head over to :ref:`Reference` to see the fine details.
