# datasette-metadata-editable

[![PyPI](https://img.shields.io/pypi/v/datasette-metadata-editable.svg)](https://pypi.org/project/datasette-metadata-editable/)
[![Changelog](https://img.shields.io/github/v/release/datasette/datasette-metadata-editable?include_prereleases&label=changelog)](https://github.com/datasette/datasette-metadata-editable/releases)
[![Tests](https://github.com/datasette/datasette-metadata-editable/workflows/Test/badge.svg)](https://github.com/datasette/datasette-metadata-editable/actions?query=workflow%3ATest)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/datasette/datasette-metadata-editable/blob/main/LICENSE)

A Datasette plugin for editing metadata on-the-fly. Work in progress.

## Installation

Install this plugin in the same environment as Datasette.

```bash
datasette install datasette-metadata-editable
```

## Usage

Usage instructions go here.

## Development

To set up this plugin locally, first checkout the code. Then create a new virtual environment:

```bash
cd datasette-metadata-editable
python3 -m venv venv
source venv/bin/activate
```

Now install the dependencies and test dependencies:

```bash
pip install -e '.[test]'
```

To run the tests:

```bash
pytest
```
