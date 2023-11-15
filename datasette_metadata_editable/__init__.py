import json
import sqlite3

import markdown2
import nh3
from datasette import Response, hookimpl, Permission, Forbidden
from sqlite_utils import Database
from typing import Optional

from .internal_migrations import internal_migrations
from functools import wraps

PERMISSION_EDIT_METADATA = "datasette-metadata-editable-edit"

cache = {}


# decorator for routes, to ensure the proper permissions are checked
def check_permission():
    def decorator(func):
        @wraps(func)
        async def wrapper(scope, receive, datasette, request):
            result = await datasette.permission_allowed(
                request.actor, PERMISSION_EDIT_METADATA, default=False
            )
            if not result:
                raise Forbidden(
                    "Permission denied for {}".format(PERMISSION_EDIT_METADATA)
                )
            return await func(scope, receive, datasette, request)

        return wrapper

    return decorator


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
            # Empty strings are added here because UNIQUE indexes in SQLite see NULLs
            # as distinct from one-another. So, use an empty string to enforce uniqueness
            "target_database": target_database or "",
            "target_table": target_table or "",
            "target_column": target_column or "",
            "key": key,
            "value": value,
        },
    )


class Routes:
    @check_permission()
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

    @check_permission()
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
def startup(datasette):
    async def inner():
        # UPSERT was added in SQLite 3.24.0 https://www.sqlite.org/changes.html#version_3_24_0
        # For now, enforce clients have a supported version
        if sqlite3.sqlite_version_info[1] < 24:
            raise Exception(
                f"SQLite version >=3.24 is required, has {sqlite3.sqlite_version}"
            )

        def migrate(connection):
            with connection:
                db = Database(connection)
                internal_migrations.apply(db)

        await datasette.get_internal_database().execute_write_fn(migrate, block=True)
        try:
            for row in await datasette.get_internal_database().execute(
                "select * from datasette_metadata_editable_entries"
            ):
                if row["target_type"] == "index":
                    cache[row["key"]] = row["value"]
                elif row["target_type"] == "table":
                    cache.setdefault("databases", {}).setdefault(
                        row["target_database"], {}
                    ).setdefault("tables", {}).setdefault(row["target_table"], {})[
                        row["key"]
                    ] = row[
                        "value"
                    ]
                    cache[row["key"]] = row["value"]
                # TODO: database, column
        except Exception as e:
            print(
                f"Exception while sourcing from datasette_metadata_editable_entries at startup: {e}"
            )

    return inner


@hookimpl
def register_permissions(datasette):
    return [
        Permission(
            name=PERMISSION_EDIT_METADATA,
            abbr=None,
            description="Ability to edit metadata",
            takes_database=False,
            takes_resource=False,
            default=False,
        ),
    ]


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
    if not request or not await datasette.permission_allowed(
        request.actor, PERMISSION_EDIT_METADATA, default=False
    ):
        return ""
    if view_name == "index":
        url = "/-/datasette-metadata-editable/edit?"
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


@hookimpl
def database_actions(datasette, actor, database):
    async def inner():
        if not await datasette.permission_allowed(
            actor, PERMISSION_EDIT_METADATA, default=False
        ):
            return []
        return [
            {
                "href": datasette.urls.path(
                    f"/-/datasette-metadata-editable/edit?db={database}"
                ),
                "label": "Edit database metadata",
            }
        ]

    return inner


@hookimpl
def table_actions(datasette, actor, database, table):
    async def inner():
        if not await datasette.permission_allowed(
            actor, PERMISSION_EDIT_METADATA, default=False
        ):
            return []
        return [
            {
                "href": datasette.urls.path(
                    f"/-/datasette-metadata-editable/edit?db={database}&table={table}"
                ),
                "label": "Edit table metadata",
            }
        ]

    return inner
