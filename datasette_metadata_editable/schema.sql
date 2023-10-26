create table datasette_metadata_editable_entries(
  -- 'index' | 'database' | 'table' | 'column'
  target_type text not null,
  target_database text,
  target_table text,
  target_column text,
  -- ex. 'description_html', 'source', 'license', 'about', etc.
  key text not null,
  value text,

  UNIQUE(target_type, target_database, target_table, target_column, key)
);
