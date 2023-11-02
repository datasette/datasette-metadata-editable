from datasette.app import Datasette
import pytest


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
