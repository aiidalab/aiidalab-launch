# Contribution guidelines

Contributions in the form of issues, comments as well as pull requests for documentation updates, fixes, and feature implementations are very welcome.

Please make sure to always create an issue for any but the most trivial changes.
Feature contributions might not be accepted in case that we determine that they do not fall into the scope of the package.
To avoid expending unnecessary effort, please make sure to create an issue for a feature proposal to provide opportunity for discussion prior to implementation.

## Testing

All tests are located within the `tests/` directory and implemented with the [pytest framework](https://pytest.org/).

Most modules have a corresponding test module (e.g. `aiidalab_launch/instance.py` and `tests/test_instance.py`) which contain unit and integration tests related to that module.

We use the [pytest fixture system](https://docs.pytest.org/en/7.1.x/explanation/fixtures.html#about-fixtures) to create an isolated environment such that the user's actual configuration and docker environment (if available) are not affected.
For example, we ensure that we monkeypatch the `Path.home()` function to not point to the actual home directory with the [`home_path` fixture](https://github.com/aiidalab/aiidalab-launch/blob/73fe854e525d1c0adfa1f92b1aa97842df5a5c16/tests/conftest.py#L90-L95).

Most fixtures that protect the user's environment are class-scoped and auto-used.
This means that they will be automatically applied even if not explicitly requested and that they can be persisted by grouping multiple tests into a test class.
We use this for example for the [instance lifecycle tests](https://github.com/aiidalab/aiidalab-launch/blob/73fe854e525d1c0adfa1f92b1aa97842df5a5c16/tests/test_cli.py#L167) to actually re-use a previously started instance, otherwise the instance would be automatically destroyed after the test function has exited.

### How to run tests

First, make sure to install the test dependencies, e.g., by executing the following command from within the repository root directory:

```console
$ pip install -e '.[tests]'
```

Next, run tests by simply executing `$ pytest`.

Some tests require a running docker engine and will be automatically skipped if the docker daemon cannot be reached.
Some tests take a significantly longer time to complete and are automatically skipped unless the `$ pytest --slow` option is provided.
The repository's CI workflows will always execute all tests.

### Test coverage

The test suite will fail in case that the overall coverage drops below a certain threshold.
The coverage of a specific patch is also automatically tested via [codecov](https://about.codecov.io/) when a pull request is created.
