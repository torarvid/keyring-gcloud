# keyring-gcloud

A keyring backend for Google Cloud Platform.

## Installation

We recommend using [uv](https://github.com/astral-sh/uv) to install this keyring
backend.

```bash
uv tool install keyring --with keyring-gcloud
```

## How it works

This backend does not store any credentials by itself. It will choose a
storage-backend by looking at all viable backends and choose the one with the
highest priority. It works by intercepting invocations of `keyring get|set`. A
`get` operation that is intercepted works like this:

1. Attempt to get the value from the storage backend
2. Decode this value as if it was written by **this backend**
   1. If decoding successful, check the expiry of the token
      1. If not expired, return the token.
   2. If decoding unsuccessful, use google-auth to fetch a new token (similar
      to doing `gcloud auth print-access-token`)
      1. Store the new token in the storage backend
      2. Return the new token

A `set` operation is simpler. It will just prepend an expiry of 1 hour to the
supplied token, encode these two values and store them in the storage backend.

## Usage

There are two ways to use this backend:

### 1: Via the `keyring` command line parameters:

AKA the "I'll use it on-demand, thank you very much" method.

```bash
export KEYRING_GCLOUD_ON=1_or_yes_or_any_string_really
keyring --keyring-backend keyring_gcloud.GoogleCloudKeyring <...>
```

The env variable `KEYRING_GCLOUD_ON` will make this backend intercept any
invocation.

### 2: Via the keyring configuration file:

In the keyring configuration file, add the following:

```toml
[backend]
default-keyring=keyring_gcloud.GoogleCloudKeyring
```

This will make `keyring` use the `GoogleCloudKeyring` backend on all calls to
`keyring get foo bar` (regardless of any `--keyring-backend` parameter). This
has some risk, since if you were to run

```bash
keyring set some-website foo@example.com mypassword
```

it is unlikely that you would want `mypassword` to have an expiry of 1 hour. To
lower this risk, you should **unset** the `KEYRING_GCLOUD_ON` environment
variable. When that env variable is **not set**, the backend only intercepts if
the `username` for the request matches `KEYRING_GCLOUD_USERNAME` (default
`oauth2accesstoken`).

So a call like

```bash
keyring get https://private-pypi.example.com/simple/ oauth2accesstoken
```

would be intercepted. Python tooling sometimes use keyring to fetch credentials
for private registries. `poetry` is an example of a service that does this with
`oauth2accesstoken` as the username). `uv` can use keyring if
`[[tool.uv.index]]` is set to a private registry and the environment variable
`UV_KEYRING_PROVIDER` is set to `subprocess`.
