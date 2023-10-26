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
