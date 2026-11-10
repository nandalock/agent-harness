# Vendored packages

`cordis/` contains the `minidsh-cordis` Python kernel from the [standalone repository](https://github.com/nandalock/minidsh-cordis), pinned to `7c594aae632a7a67b3d2a87ba2903b77ccee6d24`.

The application uses the local version `0.1.0+minidsh.3`. It adds borrowed host services, registration handles for service withdrawal, composition startup with whole-graph rollback, and partial graph replacement, optional services and native plugin declarations. The application runs lifecycle callbacks on one task so task-affine resources can close on their owning task.

To update the pin, compare the standalone changes, reapply any local patches that still apply, and run the kernel, runtime and application integration tests.
