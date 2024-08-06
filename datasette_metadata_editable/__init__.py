import datetime
import markdown2
import nh3
from datasette import Response, hookimpl, Permission, Forbidden
import json
from sqlite_utils import Database
from .internal_migrations import migrations

from functools import wraps

PERMISSION_EDIT_METADATA = "datasette-metadata-editable-edit"


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


def resolve_field(field):
    return "description_html" if field == "description_markdown" else field


def resolve_value(data, field):
    if field == "description_markdown":
        return md_to_html(data.get(field))
    return data.get(field)


async def log_edit(
    datasette, target_type, database, table, column, actor_id, fields: dict
):
    internal_db = datasette.get_internal_database()
    sql = """
    insert into datasette_metadata_editable_history
        (target_type, database_name, resource_name, column_name, actor_id, updated_at, fields_json)
            values
        (:target_type, {database_name}, {resource_name}, {column_name}, {actor_id}, :updated_at, :fields_json)
    """.format(
        database_name=database and ":database_name" or "null",
        resource_name=table and ":resource_name" or "null",
        column_name=column and ":column_name" or "null",
        actor_id=actor_id and ":actor_id" or "null",
    )
    await internal_db.execute_write(
        sql,
        {
            "target_type": target_type,
            "database_name": database,
            "resource_name": table,
            "column_name": column,
            "actor_id": actor_id,
            "updated_at": datetime.datetime.now().isoformat(),
            "fields_json": json.dumps(
                dict(
                    (key, value) for key, value in fields.items() if key != "csrftoken"
                )
            ),
        },
    )


async def get_last_edit(datasette, target_type, database, table, column):
    where_bits = ["target_type = :target_type"]
    if database:
        where_bits.append("database_name = :database_name")
    if table:
        where_bits.append("resource_name = :resource_name")
    if column:
        where_bits.append("column_name = :column_name")
    sql = """
    select * from datasette_metadata_editable_history
    where {where_clause}
    order by updated_at desc
    limit 1
    """.format(
        where_clause=" and ".join(where_bits)
    )
    internal_db = datasette.get_internal_database()
    result = await internal_db.execute(
        sql,
        {
            "target_type": target_type,
            "database_name": database,
            "resource_name": table,
            "column_name": column,
        },
    )
    first = result.first()
    if first:
        row = dict(first)
        if (row.get("fields_json") or "").strip().startswith("{"):
            row["fields"] = json.loads(row["fields_json"])
        return row
    else:
        return None


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
            target_type = "instance"

        if target_type == "instance":
            defaults = await datasette.get_instance_metadata()
        elif target_type == "database":
            defaults = await datasette.get_database_metadata(db)
        elif target_type == "table":
            defaults = await datasette.get_resource_metadata(db, table)
        elif target_type == "column":
            defaults = await datasette.get_column_metadata(db, table, column)

        # description_markdown is a special case, it comes from the edit log
        last_edit = await get_last_edit(
            datasette, target_type, database=db, table=table, column=column
        )
        if last_edit and last_edit["fields"].get("description_markdown"):
            defaults["description_markdown"] = last_edit["fields"][
                "description_markdown"
            ]

        return Response.html(
            await datasette.render_template(
                "datasette_metadata_editable_edit.html",
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
        redirect_url = None
        message = None
        target_type = data.get("target_type")
        actor_id = None
        if request.actor:
            actor_id = request.actor.get("id")
        if target_type == "instance":
            for field in [
                "title",
                "description_markdown",
                "source",
                "license",
                "source_url",
                "license_url",
            ]:
                await datasette.set_instance_metadata(
                    resolve_field(field), resolve_value(data, field)
                )
            await log_edit(
                datasette,
                target_type=target_type,
                database=None,
                table=None,
                column=None,
                actor_id=actor_id,
                fields=data,
            )
            message = "Metadata updated"
            redirect_url = datasette.urls.instance()
        elif target_type == "database":
            database = data.get("_database")
            for field in [
                "description_markdown",
                "source",
                "license",
                "source_url",
                "license_url",
            ]:
                await datasette.set_database_metadata(
                    database, resolve_field(field), resolve_value(data, field)
                )
            await log_edit(
                datasette,
                target_type=target_type,
                database=database,
                table=None,
                column=None,
                actor_id=actor_id,
                fields=data,
            )
            message = "Database metadata updated"
            redirect_url = datasette.urls.database(database)
        elif target_type == "table":
            database = data.get("_database")
            table = data.get("_table")
            for field in [
                "description_markdown",
                "source",
                "license",
                "source_url",
                "license_url",
            ]:
                await datasette.set_resource_metadata(
                    database, table, resolve_field(field), resolve_value(data, field)
                )
            await log_edit(
                datasette,
                target_type=target_type,
                database=database,
                table=table,
                column=None,
                actor_id=actor_id,
                fields=data,
            )
            message = "Table metadata updated"
            redirect_url = datasette.urls.table(database, table)
        elif target_type == "column":
            database = data.get("_database")
            table = data.get("_table")
            column = data.get("_column")
            for field in [
                "description_markdown",
                "source",
                "license",
                "source_url",
                "license_url",
            ]:
                await datasette.set_column_metadata(
                    database,
                    table,
                    column,
                    resolve_field(field),
                    resolve_value(data, field),
                )
            await log_edit(
                datasette,
                target_type=target_type,
                database=None,
                table=table,
                column=column,
                actor_id=actor_id,
                fields=data,
            )
            message = "Column metadata updated"
            redirect_url = datasette.urls.table(database, table)
        if not redirect_url:
            return Response.html("error", status=400)
        else:
            if message:
                datasette.add_message(request, message, type=datasette.INFO)
            return Response.redirect(redirect_url)


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
def register_routes():
    return [
        (r"^/-/datasette-metadata-editable/edit$", Routes.edit_page),
        (r"^/-/datasette-metadata-editable/api/edit$", Routes.api_edit),
    ]


@hookimpl
def homepage_actions(datasette, actor):
    async def inner():
        if not await datasette.permission_allowed(
            actor, PERMISSION_EDIT_METADATA, default=False
        ):
            return []
        return [
            {
                "href": datasette.urls.path("/-/datasette-metadata-editable/edit"),
                "label": "Edit instance metadata",
                "description": "Set the title and description for this instance",
            }
        ]

    return inner


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
                "description": "Set the description, source and license for this database",
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
                "description": "Set the description, source and license for this table",
            }
        ]

    return inner


@hookimpl
def startup(datasette):
    async def inner():
        def migrate(connection):
            with connection:
                db = Database(connection)
                migrations.apply(db)

        await datasette.get_internal_database().execute_write_fn(migrate, block=True)

    return inner
