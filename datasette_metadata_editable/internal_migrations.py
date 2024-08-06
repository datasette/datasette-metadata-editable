from sqlite_utils import Database
from sqlite_migrate import Migrations

migrations = Migrations("datasette-metadata-editable.internal")


@migrations()
def m001_initialize_datasette_metadata_editable(db: Database):
    db.executescript(
        """
    create table datasette_metadata_editable_entries(
        -- 'index' | 'database' | 'table' | 'column'
        target_type text not null,
        -- Uses empty string for "null" to enforce uniqueness
        target_database text not null,
        -- Uses empty string for "null" to enforce uniqueness
        target_table text not null,
        -- Uses empty string for "null" to enforce uniqueness
        target_column text not null,
        -- ex. 'description_html', 'source', 'license', 'about', etc.
        key text not null,
        value text,
        UNIQUE(target_type, target_database, target_table, target_column, key)
    );
    """
    )


@migrations()
def m002_migrate_datasette_metadata_editable_to_system_tables(db: Database):
    if (
        db["datasette_metadata_editable_entries"].exists()
        and db["metadata_instance"].exists()
    ):
        for row in db["datasette_metadata_editable_entries"].rows:
            if row["target_type"] == "index":
                db["metadata_instance"].insert(
                    {
                        "key": row["key"],
                        "value": row["value"],
                    },
                    replace=True,
                )
            elif row["target_type"] == "database":
                db["metadata_databases"].insert(
                    {
                        "database_name": row["target_database"],
                        "key": row["key"],
                        "value": row["value"],
                    }
                )
            elif row["target_type"] == "table":
                db["metadata_resources"].insert(
                    {
                        "database_name": row["target_database"],
                        "resource_name": row["target_table"],
                        "key": row["key"],
                        "value": row["value"],
                    }
                )
            elif row["target_type"] == "column":
                db["metadata_columns"].insert(
                    {
                        "database_name": row["target_database"],
                        "resource_name": row["target_table"],
                        "column_name": row["target_column"],
                        "key": row["key"],
                        "value": row["value"],
                    }
                )
        db["datasette_metadata_editable_entries"].drop()


@migrations()
def m003_edit_history_table(db: Database):
    table = db["datasette_metadata_editable_history"].create(
        {
            "id": int,
            "target_type": str,
            "database_name": str,
            "resource_name": str,
            "column_name": str,
            "actor_id": str,
            "updated_at": str,
            "fields_json": str,
        },
        pk="id",
    )
    table.create_index(
        ["target_type", "database_name", "resource_name", "column_name", "updated_at"]
    )
