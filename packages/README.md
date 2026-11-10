# Python package layout

Agent 服务与循环插件位于 [`agent/`](agent/README.md)，公共会话事实层位于
[`session/core/`](session/core/README.md)。默认装配通过插件工厂驱动对话；
后端不直接创建循环。

Python plugin and library packages use the same flat source layout:

```text
package/
├─ pyproject.toml
└─ src/
   ├─ __init__.py
   └─ plugin.py
```

The import name is mapped explicitly, rather than repeated as a source directory:

```toml
[tool.setuptools]
packages = ["agent_platform_tools_default"]

[tool.setuptools.package-dir]
agent_platform_tools_default = "src"
```

Nested Python packages must also appear in `packages`, e.g.
`agent_platform_sandbox.backends`; their directories remain under `src/`.
Runtime data such as `py.typed`, default YAML, skill documents and native runner
manifests are declared through `tool.setuptools.package-data`.

Plugin module exports and Python imports are independent of disk layout and retain
their existing names. After changing a package mapping, reinstall the packages:

```bash
python -m pip install -r requirements-plugins.txt
python -m pip install -e ./packages/plugin/examples/echo-plugin
```

`client/` and its browser plugins use `package.json` and are unaffected by Python
package mapping. Plugin-generated build artifacts, dependency directories and
runtime credentials are not source packages or package data.

Setuptools' default editable mapping uses import hooks. Static analyzers that do
not execute those hooks may need a regular wheel installation for dependency
discovery. SDK typing tests materialize the regular package layout and still
check that incompatible service registrations are rejected.
