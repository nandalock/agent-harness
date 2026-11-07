import asyncio
import unittest

from pydantic import BaseModel

from agent_platform_plugin_runtime import MappingCatalog, PluginRuntime
from agent_platform_plugin_sdk import PluginSpec, SdkModel, ServiceRequirement
from agent_platform_rpc_gateway import (
    RPC_GATEWAY,
    RpcContext,
    RpcGatewayPlugin,
    RpcMethodContract,
    RpcMethodNotFound,
)


class Params(BaseModel):
    value: int


class Result(BaseModel):
    value: int


class _Config(SdkModel):
    pass


class _Controller:
    def __init__(self, method: str):
        self.method = method
        self.spec = PluginSpec(
            name="test.controller", version="0.1.0",
            requires=(ServiceRequirement(service=RPC_GATEWAY.ref),),
        )
        self.config_model = _Config

    async def setup(self, ctx, config):
        gateway = ctx.require(RPC_GATEWAY)

        async def echo(params: Params, context: RpcContext):
            return Result(value=params.value)

        ctx.track(gateway.register(RpcMethodContract(self.method, Params, Result), echo))


class _GatewayTest(unittest.IsolatedAsyncioTestCase):
    def runtime(self, method: str) -> PluginRuntime:
        return PluginRuntime(
            {"plugins": [
                {"id": "gateway", "name": "agent-platform.rpc-gateway"},
                {"id": "controller", "name": "test.controller"},
            ]},
            catalog=MappingCatalog({
                "agent-platform.rpc-gateway": RpcGatewayPlugin,
                "test.controller": lambda: _Controller(method),
            }),
        )

    async def test_unload_revokes_methods_and_runtimes_are_isolated(self):
        first, second = self.runtime("test.first"), self.runtime("test.second")
        await first.start()
        await second.start()
        try:
            first_gateway = first.require(RPC_GATEWAY)
            self.assertEqual(first_gateway.methods(), ("test.first",))
            self.assertEqual(second.require(RPC_GATEWAY).methods(), ("test.second",))
            await first.aclose()
            with self.assertRaises(RpcMethodNotFound):
                await first_gateway.invoke("test.first", {"value": 1}, RpcContext(tenant_id=1))
            # The second runtime keeps its own method table.
            self.assertEqual(second.require(RPC_GATEWAY).methods(), ("test.second",))
        finally:
            await second.aclose()


if __name__ == "__main__":
    unittest.main()
