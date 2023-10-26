import json
import sqlite3

import markdown2
import nh3
from datasette import Response, hookimpl
from sqlite_utils import Database
from typing import Optional

from .internal_migrations import internal_migrations

cache = {}


def md_to_html(md: str):
    raw_html = markdown2.markdown(md)
    return nh3.clean(raw_html)


async def insert_index_entry(db, cache, key, value):
    return await insert_entry(db, cache, "index", None, None, None, key, value)


async def insert_database_entry(db, cache, database, key, value):
    return await insert_entry(db, cache, "database", database, None, None, key, value)


async def insert_table_entry(db, cache, database, table, key, value):
    return await insert_entry(db, cache, "table", database, table, None, key, value)


async def insert_column_entry(db, cache, database, table, column, key, value):
    return await insert_entry(db, cache, "column", database, table, column, key, value)


async def insert_entry(
    db,
    cache,
    target_type: str,
    target_database: Optional[str],
    target_table: Optional[str],
    target_column: Optional[str],
    key: str,
    value: Optional[str],
):
    if target_type == "index":
        cache[key] = md_to_html(value) if key.endswith("_html") else value
    elif target_type == "database":
        cache.setdefault("databases", {}).setdefault(target_database, {})[key] = (
            md_to_html(value) if key.endswith("_html") else value
        )
    elif target_type == "table":
        cache.setdefault("databases", {}).setdefault(target_database, {}).setdefault(
            "tables", {}
        ).setdefault(target_table, {})[key] = (
            md_to_html(value) if key.endswith("_html") else value
        )
    elif target_type == "column":
        cache.setdefault("databases", {}).setdefault(target_database, {}).setdefault(
            "tables", {}
        ).setdefault(target_table, {}).setdefault("columns", {})[key] = (
            md_to_html(value) if key.endswith("_html") else value
        )

    return await db.execute_write(
        """
        INSERT INTO datasette_metadata_editable_entries(target_type, target_database, target_table, target_column, key, value)
        VALUES (:target_type, :target_database, :target_table, :target_column, :key, :value)
        ON CONFLICT(target_type, target_database, target_table, target_column, key)
          DO UPDATE SET value = :value

      """,
        {
            "target_type": target_type,
            "target_database": target_database,
            "target_table": target_table,
            "target_column": target_column,
            "key": key,
            "value": value,
        },
    )


class Routes:
    async def edit_page(scope, receive, datasette, request):
        db = request.args.get("db")
        table = request.args.get("table")
        column = request.args.get("column")

        if db and not table:
            target_type = "database"
        elif db and table and column:
            target_type = "column"
        elif db and table:
            target_type = "table"
        else:
            target_type = "index"

        if target_type == "index":
            defaults = cache or {}
        if target_type == "database":
            defaults = (cache.get("databases") or {}).get(db) or {}
        if target_type == "table":
            defaults = (
                ((cache.get("databases") or {}).get(db) or {}).get("tables") or {}
            ).get(table) or {}
        if target_type == "column":
            table = (
                ((cache.get("databases") or {}).get(db) or {}).get("tables") or {}
            ).get(table) or {}
            defaults = {"description": (table.get("columns") or {}).get(column)} or {}
        return Response.html(
            await datasette.render_template(
                "edit.html",
                {
                    "target_type": target_type,
                    "defaults": defaults,
                    "database": db,
                    "table": table,
                    "column": column,
                },
                request=request,
            )
        )

    async def api_edit(scope, receive, datasette, request):
        assert request.method == "POST"
        data = await request.post_vars()
        internal_db = datasette.get_internal_database()

        target_type = data.get("target_type")
        if target_type == "index":
            for field in ["title", "description_html", "source", "license"]:
                await insert_index_entry(internal_db, cache, field, data.get(field))
            return Response.redirect("/")

        elif target_type == "database":
            database = data.get("_database")
            for field in ["description_html", "source", "license"]:
                await insert_database_entry(
                    internal_db, cache, database, field, data.get(field)
                )
            return Response.redirect(f"/{database}")
        elif target_type == "table":
            database = data.get("_database")
            table = data.get("_table")
            for field in ["description_html", "source", "license"]:
                await insert_table_entry(
                    internal_db, cache, database, table, field, data.get(field)
                )
            return Response.redirect(f"/{database}/{table}")
        elif target_type == "column":
            database = data.get("_database")
            table = data.get("_table")
            column = data.get("_column")
            for field in ["description_html", "source", "license"]:
                await insert_column_entry(
                    internal_db, cache, database, table, column, field, data.get(field)
                )
            return Response.redirect(f"/{database}/{table}")
        return Response.html("error", status=400)


@hookimpl
async def startup(datasette):
    # UPSERT was added in SQLite 3.24.0 https://www.sqlite.org/changes.html#version_3_24_0
    # For now, enforce clients have a supported version
    if sqlite3.sqlite_version_info[1] < 24:
        raise Exception(
            f"SQLite version >=3.24 is required, has {sqlite3.sqlite_version}"
        )

    def migrate(connection):
        db = Database(connection)
        internal_migrations.apply(db)

        for row in db.execute("select * from datasette_metadata_editable_entries"):
            if row["target_type"] == "index":
                cache[row["key"]] = row["value"]

    await datasette.get_internal_database().execute_write_fn(migrate)


@hookimpl
def get_metadata(datasette, key, database, table):
    return cache


@hookimpl
def register_routes():
    return [
        (r"^/-/datasette-metadata-editable/edit$", Routes.edit_page),
        (r"^/-/datasette-metadata-editable/api/edit$", Routes.api_edit),
    ]


@hookimpl
async def extra_body_script(
    template, database, table, columns, view_name, request, datasette
):
    if view_name in ("index", "database", "table"):
        url = "/-/datasette-metadata-editable/edit?"
        if view_name in ["database", "table"]:
            url += f"&db={database}"
        if view_name in ["table"]:
            url += f"&table={table}"
        return f"""
          const editMetadata = document.createElement("a")
          editMetadata.textContent = "Edit metadata"
          editMetadata.setAttribute('href', {json.dumps(url)})

          const metadataElement = document.querySelector('.metadata-description');
          if(metadataElement)
              metadataElement.appendChild(editMetadata)
          else
            (document.querySelector('.page-header') || document.querySelector('h1')).after(editMetadata)
        """
    return ""


@hookimpl
def extra_js_urls(template, database, table, columns, view_name, request, datasette):
    if view_name in {"table", "query", "database"}:
        return [
            datasette.urls.path(
                "/-/static-plugins/datasette-metadata-editable/plugin.js"
            )
        ]
