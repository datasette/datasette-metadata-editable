from datasette.app import Datasette
from datasette_metadata_editable import internal_migrations
import pytest
import sqlite_utils


@pytest.mark.asyncio
async def test_plugin_is_installed():
    datasette = Datasette(memory=True)
    response = await datasette.client.get("/-/plugins.json")
    assert response.status_code == 200
    installed_plugins = {p["name"] for p in response.json()}
    assert "datasette-metadata-editable" in installed_plugins


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,expected_url",
    (
        ("/", "/-/datasette-metadata-editable/edit"),
        (
            "/test_action_menus",
            "/-/datasette-metadata-editable/edit?db=test_action_menus",
        ),
        (
            "/test_action_menus/foo",
            "/-/datasette-metadata-editable/edit?db=test_action_menus&amp;table=foo",
        ),
    ),
)
async def test_action_menus(path, expected_url):
    datasette = Datasette(
        config={"permissions": {"datasette-metadata-editable-edit": {"id": ["root"]}}},
    )
    await datasette.refresh_schemas()
    db = datasette.add_memory_database("test_action_menus")
    await db.execute_write("create table if not exists foo (id integer primary key)")
    fragment = '"{}"'.format(expected_url)
    # Anonymous
    anon_response = await datasette.client.get(path)
    assert fragment not in anon_response.text
    # User but not the root user
    user_response = await datasette.client.get(
        path, cookies={"ds_actor": datasette.client.actor_cookie({"id": "user"})}
    )
    assert fragment not in user_response.text
    # root user
    root_response = await datasette.client.get(
        path, cookies={"ds_actor": datasette.client.actor_cookie({"id": "root"})}
    )
    assert fragment in root_response.text


@pytest.mark.asyncio
async def test_basic():
    datasette = Datasette(
        memory=True,
        config={"permissions": {"datasette-metadata-editable-edit": {"id": ["root"]}}},
    )
    await datasette.refresh_schemas()
    assert (await datasette.get_instance_metadata()).get("title") is None

    cookies = {"ds_actor": datasette.sign({"a": {"id": "root"}}, "actor")}
    response = await datasette.client.get(
        "/-/datasette-metadata-editable/edit", cookies=cookies
    )
    csrftoken = response.cookies["ds_csrftoken"]
    cookies["ds_csrftoken"] = csrftoken

    await datasette.client.post(
        "/-/datasette-metadata-editable/api/edit",
        cookies=cookies,
        data={"csrftoken": csrftoken, "target_type": "instance", "title": "yo"},
    )

    assert (await datasette.get_instance_metadata())["title"] == "yo"

    await datasette.client.post(
        "/-/datasette-metadata-editable/api/edit",
        cookies=cookies,
        data={"csrftoken": csrftoken, "target_type": "instance", "title": "yo2"},
    )
    assert (await datasette.get_instance_metadata())["title"] == "yo2"


@pytest.mark.asyncio
async def test_edit_table():
    datasette = Datasette(
        memory=True,
        config={"permissions": {"datasette-metadata-editable-edit": {"id": ["root"]}}},
    )
    await datasette.refresh_schemas()
    db = datasette.add_memory_database("test-db-with-hyphens")
    await db.execute_write(
        "create table table_with_underscores (id integer primary key)"
    )
    metadata_before = (
        await datasette.client.get(
            "/test-db-with-hyphens/table_with_underscores.json?_extra=metadata"
        )
    ).json()
    assert metadata_before["metadata"] == {"columns": {}}
    # Now make the edit
    cookies = {"ds_actor": datasette.sign({"a": {"id": "root"}}, "actor")}
    response = await datasette.client.get(
        "/-/datasette-metadata-editable/edit", cookies=cookies
    )
    csrftoken = response.cookies["ds_csrftoken"]
    cookies["ds_csrftoken"] = csrftoken

    response2 = await datasette.client.post(
        "/-/datasette-metadata-editable/api/edit",
        cookies=cookies,
        data={
            "csrftoken": csrftoken,
            "target_type": "table",
            "_database": "test-db-with-hyphens",
            "_table": "table_with_underscores",
            "description_html": "<b>New description</b>",
            "license": "MIT",
            "source": "New source",
        },
    )
    assert response2.status_code == 302

    # Metadata should have been updated
    metadata_after = (
        await datasette.client.get(
            "/test-db-with-hyphens/table_with_underscores.json?_extra=metadata"
        )
    ).json()
    assert metadata_after["metadata"] == {
        "description_html": "<p><b>New description</b></p>\n",
        "license": "MIT",
        "license_url": None,
        "source": "New source",
        "source_url": None,
        "columns": {},
    }


@pytest.mark.asyncio
async def test_metadata_does_not_cause_500_errors(tmpdir):
    # The following records used to cause a 500 error
    # https://github.com/datasette/datasette-metadata-editable/issues/2
    bad_rows = """
    INSERT INTO "datasette_metadata_editable_entries"
        (target_type, target_database, target_table, target_column, key, value)
    VALUES
        ('table','content','pypi_releases','','description_html','table');
    INSERT INTO "datasette_metadata_editable_entries"
        (target_type, target_database, target_table, target_column, key, value)
    VALUES
        ('table','content','pypi_releases','','source','');
    INSERT INTO "datasette_metadata_editable_entries"
        (target_type, target_database, target_table, target_column, key, value)
    VALUES
        ('table','content','pypi_releases','','license','');
    """
    internal = str(tmpdir / "internal.db")
    content = str(tmpdir / "content.db")
    content_db = sqlite_utils.Database(content)
    content_db["pypi_releases"].create({"name": str, "version": str})

    internal_db = sqlite_utils.Database(internal)
    # Run migrations to create tables
    internal_migrations.internal_migrations.apply(internal_db)

    internal_db.executescript(bad_rows)

    datasette = Datasette(
        [content],
        internal=internal,
    )
    await datasette.refresh_schemas()

    # Server should not 500
    for path in ("/", "/content"):
        response = await datasette.client.get(path)
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_metadata_survives_server_restart(tmpdir):
    internal = str(tmpdir / "internal.db")
    one = str(tmpdir / "one.db")
    two = str(tmpdir / "two.db")
    for path in (internal, one, two):
        sqlite_utils.Database(path).vacuum()
    datasette = Datasette(
        [one, two],
        config={"permissions": {"datasette-metadata-editable-edit": {"id": ["root"]}}},
        internal=internal,
    )
    await datasette.refresh_schemas()
    db = datasette.get_database("one")
    await db.execute_write("create table t(id integer primary key)")
    cookies = {"ds_actor": datasette.sign({"a": {"id": "root"}}, "actor")}
    response = await datasette.client.get(
        "/-/datasette-metadata-editable/edit", cookies=cookies
    )
    csrftoken = response.cookies["ds_csrftoken"]
    cookies["ds_csrftoken"] = csrftoken

    response2 = await datasette.client.post(
        "/-/datasette-metadata-editable/api/edit",
        cookies=cookies,
        data={
            "csrftoken": csrftoken,
            "target_type": "database",
            "_database": "one",
            "description_html": "DESCRIBED!",
        },
    )
    assert response2.status_code == 302

    # Check the metadata was stored
    sqlite_db = sqlite_utils.Database(internal)
    assert [row for row in sqlite_db["metadata_databases"].rows] == [
        {
            "database_name": "one",
            "key": "description_html",
            "value": "<p>DESCRIBED!</p>\n",
        },
        {"database_name": "one", "key": "source", "value": None},
        {"database_name": "one", "key": "license", "value": None},
        {"database_name": "one", "key": "source_url", "value": None},
        {"database_name": "one", "key": "license_url", "value": None},
    ]

    # Now restart the server
    datasette2 = Datasette(
        [one, two],
        config={"permissions": {"datasette-metadata-editable-edit": {"id": ["root"]}}},
        internal=internal,
        pdb=True,
    )
    # Metadata should have been updated and server should not have crashed
    root_response = await datasette2.client.get("/")
    assert root_response.status_code == 200
    assert "DESCRIBED" in (await datasette2.client.get("/one")).text


@pytest.mark.asyncio
async def test_migrations():
    datasette = Datasette()
    await datasette.refresh_schemas()
    internal_db = datasette.get_internal_database()
    await internal_db.execute_write_fn(
        lambda conn: internal_migrations.m001_initialize_datasette_metadata_editable(
            sqlite_utils.Database(conn)
        )
    )
    internal_tables = await internal_db.table_names()
    assert set(internal_tables) == {
        "catalog_databases",
        "catalog_tables",
        "catalog_columns",
        "catalog_indexes",
        "catalog_foreign_keys",
        "metadata_instance",
        "metadata_databases",
        "metadata_resources",
        "metadata_columns",
        "datasette_metadata_editable_entries",
    }
    # Now insert a bunch of fake edits
    await internal_db.execute_write(
        """
        insert into datasette_metadata_editable_entries
        (target_type, target_database, target_table, target_column, key, value)
        values
        ('instance', '', '', '', 'title', 'Hello'),
        ('database', 'db1', '', '', 'title', 'DB1'),
        ('table', 'db1', 'table1', '', 'title', 'Table 1'),
        ('column', 'db1', 'table1', 'column1', 'title', 'Column 1')
    """
    )
    # Run the second migration
    await internal_db.execute_write_fn(
        lambda conn: internal_migrations.m002_migrate_datasette_metadata_editable_to_system_tables(
            sqlite_utils.Database(conn)
        )
    )

    # Check the entries have been moved
    def get_all(conn):
        db = sqlite_utils.Database(conn)
        return {
            table: list(db[table].rows)
            for table in db.table_names()
            if table.startswith("metadata_")
        }

    fetched = await internal_db.execute_fn(get_all)
    assert fetched == {
        "metadata_instance": [],
        "metadata_databases": [
            {"database_name": "db1", "key": "title", "value": "DB1"}
        ],
        "metadata_resources": [
            {
                "database_name": "db1",
                "resource_name": "table1",
                "key": "title",
                "value": "Table 1",
            }
        ],
        "metadata_columns": [
            {
                "database_name": "db1",
                "resource_name": "table1",
                "column_name": "column1",
                "key": "title",
                "value": "Column 1",
            }
        ],
    }
