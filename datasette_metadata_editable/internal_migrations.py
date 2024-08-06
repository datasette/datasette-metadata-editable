from sqlite_utils import Database
from sqlite_migrate import Migrations
from pathlib import Path

internal_migrations = Migrations("datasette-metadata-editable.internal")

SCHEMA = (Path(__file__).parent / "schema.sql").read_text()


@internal_migrations()
def m001_initialize_datasette_metadata_editable(db: Database):
    db.executescript(SCHEMA)


@internal_migrations()
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
