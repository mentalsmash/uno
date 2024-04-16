# Contribute to uno

- [Development](#development)
  - [Release Process](#release-process)
  - [Pull Request Process](#pull-request-process)
  - [Coding Style](#coding-style)
- [Environment Setup](#environment-setup)
  - [pipx + poetry](#pipx--poetry)
  - [venv + pip](#venv--pip)
  - [Codespaces](#codespaces)
- [Testing](#testing)
  - [Local Testing](#local-testing)
  - [Local Testing for ARM](#local-testing-for-arm)

## Development

`uno` is set up with a CI/CD development workflow that automatically generate
new releases whenever new commits or tags are pushed to the repository.

The workflow requires for all contributions to be made via a pull request
to the main development branch.

### Release Process

A new "nightly" release is automatically triggered whenever commits are pushed
to the main development branch (`master`).

A new "stable" release is triggered whenever a tag is pushed to the repository.

The release process consists of the following steps:

- Build a multi-platform Docker image from the referenced commit, and push it
  as private Package `mentalsmash/uno-dev:<tag>` to GitHub's Container registry.

- Test the image by using it to run `uno`'s full test suite on each target platform.

- Re-tag the image as `mentalsmash/uno:<tag>` and push it to both Docker Hub (as a
  public image), and to GitHub (as an "internal" Package for the mentalsmash
  organization).

- Update the "release badges" published in the README.

The `<tag>` used by the generated image depends on the type of release:

| Event | Release Type | Image Tag |
|-------|--------------|-----------|
| push tag without a `/` in the name | stable | `latest` |
| push commit to `master` | nightly | `nightly` |

### Pull Request Process

New commits can only be merged to the main development branch via pull request.
In order for a pull request to be accepted it must pass all required checks:

- At least one maintainer must have reviewed and approved the changes.

- The changes must pass both the "basic" and "full" validation suites.

A "basic" validation will be triggered as soon as a non-draft pull request is opened.
If a pull request is opened as draft, the build will be triggered once the PR is
"ready for review". Every new commit pushed to the PR branch after that will:

- Invalidate any approval that the PR received before the push.

- Cancel (if already in progress) and trigger a new "basic" build.

The "full" validation will be triggered every time the PR transitions into "accepted" state.

Each validation workflow will target one or more platforms, and for each configuration it will:

- Build a test Docker image for the selected platform.

- Run `uno`'s full test suite.

The difference between the two validation workflows lies only in the number of "flavors" and
platforms that they test:

| Build Type | amd64 | arm64 |
|------------|-------|-------|
| basic      |:white_check_mark:|:x:|
| full       |:x:|:white_check_mark:|

### Coding Style

`uno` uses [ruff](https://github.com/astral-sh/ruff) to automatically enforce a consistent
coding style.

The tool is installed with the `dev` dependency group, and it is run automatically
before every `git` commit. You can also run the checks manually:

```sh
# Enable virtual environment
. .venv/bin/activate

# Run git hooks (both linter and formatter)
pre-commit run --all

# Only linter
ruff check 

# Only formatter
ruff format
```

### Environment Setup

#### venv + pip

1. Install the `venv` module:

   ```sh
   sudo apt-get install -y python3-venv
   ```

2. Clone `uno`'s repository:

   ```sh
   git clone --recurse-submodules https://github.com/mentalsmash/uno
   ```

3. Create a virtual environment:

   ```sh
   cd uno

   python3 -m venv .venv
   ```

4. (Optional) Make sure `pip` and `setuptools` are up to date:

   ```sh
   .venv/bin/pip install -U pip setuptools
   ```

5. Install `uno` and its dependencies:

   ```sh
   .venv/bin/pip install -e .
   ```

6. Install `git` commit hooks:

   ```sh
   .venv/bin/pre-commit install
   ```

#### Codespaces

`uno` includes a [configuration file](.devcontainer/devcontainer.json) for a [devcontainer](https://containers.dev/),
which can be used to spin up a development environment using [Codespaces](https://github.com/features/codespaces),
(and some of the free hours that most accounts receive from GitHub).

### RTI Connext DDS

By default, `uno` uses [RTI Connext DDS](https://www.rti.com) to implement a "synchronization databus" between
its agents. A valid RTI license file must be provided via the `RTI_LICENSE_FILE` environment variable.

[You can request a free evaluation license from RTI](https://www.rti.com/free-trial).

If you don't have/don't want to get a free license from RTI, you can still use `uno` but the agent functionality
will not be available, and the UVN will need to be reconfigured by hand.

### Testing

#### Local Testing

`uno` includes a [Docker Compose file](compose.yaml) that can be used to build the development image
required to run integration tests.

The image also supports mounting the local copy of the `uno` package for testing.

1. Build the image (`mentalsmash/uno-test-runner:latest`) with:

   ```sh
   cd uno/

   docker compose build test-runner
   ```

2. Use it to run the unit tests without having to install `uno`'s system dependencies

   ```sh
   docker run --rm -v $(pwd):/uno -w /uno \
     mentalsmash/uno-test-runner:latest \
     pytest -s -v test/unit
   ```

3. Use it (implicitly) to run the integration tests:

   ```sh
   DEV=y pytest -s -v test/integration
   ```

   The `DEV` variable tells the integration test framework to mount the `uno` package from the host
   to test changes made to it after building the image.
   If unspecified, the image will use the version of `uno` installed during build.

   For increased logging verbosity try:

   ```sh
   VERBOSITY=debug DEBUG=y DEV=y pytest -s -v test/integration
   ```

   To persist the test directories created by each experiment
   after the tester terminates:

   ```sh
   TEST_DIR=/tmp/uno-test DEV=y pytest -s -v test/integration
   ```

4. You can also build a test "release" image (`mentalsmash/uno:dev`) with:

   ```sh
   docker compose build uno
   ```

   NOTE: this image does not install `uno` in "editable" mode and henve it will not pick
   up a local copy mounted as a volume.

#### Local Testing for ARM

The `arm64` image can be built locally using QEMU, but running tests with it is not recommended
because of the crawling speed at which emulated instructions run.

Instead, `uno` CI/CD infrastructure includes `arm64` runners that can run the tests natively.
The tests are automatically triggered during every release, and for every "full" PR validation.

Nevertheless, it can be useful to test building the release image locally, which can be achieved with:

```sh
docker compose build uno-arm64
```

If you really want to test the local copy of `uno` on an emulated `arm64` container, you
can build an `arm64` "test runner" with:

```sh
docker compose build test-runner-arm64
```

WARNING: in order to use these commands, you might have to enable QEMU emulation using the
[tonistiigi/binfmt](https://github.com/tonistiigi/binfmt) image:

```sh
docker run --privileged --rm tonistiigi/binfmt --install all
```

If you enounter any emulation problems while using this image (e.g. QEMU segfaults), you can
try replacing it with [multiarch/qemu-user-static](https://github.com/multiarch/qemu-user-static):

```sh
docker run --rm --privileged multiarch/qemu-user-static --reset -p yes -c yes
```
