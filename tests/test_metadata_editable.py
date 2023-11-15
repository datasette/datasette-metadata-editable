from datasette.app import Datasette
from datasette_metadata_editable.internal_migrations import internal_migrations
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
async def test_basic(snapshot):
    datasette = Datasette(
        memory=True,
        metadata={
            "permissions": {"datasette-metadata-editable-edit": {"id": ["root"]}}
        },
    )
    assert datasette.metadata("title") is None

    cookies = {"ds_actor": datasette.sign({"a": {"id": "root"}}, "actor")}
    response = await datasette.client.get(
        "/-/datasette-metadata-editable/edit", cookies=cookies
    )
    csrftoken = response.cookies["ds_csrftoken"]
    cookies["ds_csrftoken"] = csrftoken

    await datasette.client.post(
        "/-/datasette-metadata-editable/api/edit",
        cookies=cookies,
        data={"csrftoken": csrftoken, "target_type": "index", "title": "yo"},
    )

    async def all_entries():
        return [
            dict(row)
            for row in (
                await datasette.get_internal_database().execute(
                    "select * from datasette_metadata_editable_entries"
                )
            ).rows
        ]

    assert datasette.metadata("title") == "yo"
    assert await all_entries() == snapshot(name="entry rows initial")

    await datasette.client.post(
        "/-/datasette-metadata-editable/api/edit",
        cookies=cookies,
        data={"csrftoken": csrftoken, "target_type": "index", "title": "yo2"},
    )
    assert datasette.metadata("title") == "yo2"
    assert await all_entries() == snapshot(name="entry rows updated")


@pytest.mark.asyncio
async def test_edit_table():
    datasette = Datasette(
        memory=True,
        metadata={
            "permissions": {"datasette-metadata-editable-edit": {"id": ["root"]}}
        },
    )
    db = datasette.add_memory_database("test-db-with-hyphens")
    await db.execute_write(
        "create table table_with_underscores (id integer primary key)"
    )
    metadata_before = (
        await datasette.client.get(
            "/test-db-with-hyphens/table_with_underscores.json?_extra=metadata"
        )
    ).json()
    assert metadata_before["metadata"] == {
        "source": None,
        "source_url": None,
        "license": None,
        "license_url": None,
        "about": None,
        "about_url": None,
    }
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
        "source": "New source",
        "license": "MIT",
        "source_url": None,
        "license_url": None,
        "about": None,
        "about_url": None,
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
    internal_migrations.apply(internal_db)

    internal_db.executescript(bad_rows)

    datasette = Datasette(
        [content],
        internal=internal,
    )

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
        metadata={
            "permissions": {"datasette-metadata-editable-edit": {"id": ["root"]}}
        },
        internal=internal,
    )
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
    assert list(
        sqlite_db.query(
            "select * from datasette_metadata_editable_entries where value != ''"
        )
    ) == [
        {
            "target_type": "database",
            "target_database": "one",
            "target_table": "",
            "target_column": "",
            "key": "description_html",
            "value": "DESCRIBED!",
        }
    ]

    # Now restart the server
    datasette2 = Datasette(
        [one, two],
        metadata={
            "permissions": {"datasette-metadata-editable-edit": {"id": ["root"]}}
        },
        internal=internal,
        pdb=True,
    )
    # Metadata should have been updated and server should not have crashed
    root_response = await datasette2.client.get("/")
    assert root_response.status_code == 200
    assert "DESCRIBED" in (await datasette2.client.get("/one")).text
