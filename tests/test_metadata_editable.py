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
    datasette = Datasette(memory=True)
    assert datasette.metadata("title") is None

    cookies = {"ds_actor": datasette.sign({"a": {"id": "root"}}, "actor")}
    response = await datasette.client.get(
        "/-/datasette-metadata-editable/edit", cookies=cookies
    )
    csrftoken = response.cookies["ds_csrftoken"]
    cookies["ds_csrftoken"] = csrftoken

    await datasette.client.post(
        "/-/datasette-metadata-editable/api/edit",
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
        data={"csrftoken": csrftoken, "target_type": "index", "title": "yo2"},
    )
    assert datasette.metadata("title") == "yo2"
    assert await all_entries() == snapshot(name="entry rows updated")
