import asyncio
import unittest

from pydantic import BaseModel

from agent_platform_rpc_connection import RpcConnection
from agent_platform_rpc_gateway import RpcContext, RpcError, RpcGateway, RpcMethodContract


class Params(BaseModel):
    value: int


class Result(BaseModel):
    value: int


class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.gateway = RpcGateway()
        self.connection = RpcConnection(self.gateway)

        async def echo(params: Params, context: RpcContext):
            return Result(value=params.value)

        async def fail(params: Params, context: RpcContext):
            raise RpcError("example/failed", "expected failure")

        async def explode(params: Params, context: RpcContext):
            raise RuntimeError("secret database detail")

        self.registrations = [
            self.gateway.register(RpcMethodContract("example.echo", Params, Result), echo),
            self.gateway.register(RpcMethodContract("example.fail", Params, Result), fail),
            self.gateway.register(RpcMethodContract("example.explode", Params, Result), explode),
        ]

    async def asyncTearDown(self):
        for registration in self.registrations:
            await registration.aclose()

    async def test_request_id_is_echoed_and_result_is_wrapped(self):
        response = await self.connection.dispatch(
            {"jsonrpc": "2.0", "id": "request-1", "method": "example.echo", "params": {"value": 3}},
            tenant_id=1,
        )
        self.assertEqual(response, {"jsonrpc": "2.0", "id": "request-1", "result": {"value": 3}})

    async def test_unknown_method_and_invalid_params_use_protocol_codes(self):
        unknown = await self.connection.dispatch(
            {"jsonrpc": "2.0", "id": 1, "method": "example.missing", "params": {}},
            tenant_id=1,
        )
        self.assertEqual(unknown["error"]["code"], -32601)
        invalid = await self.connection.dispatch(
            {"jsonrpc": "2.0", "id": 2, "method": "example.echo", "params": {"value": "x"}},
            tenant_id=1,
        )
        self.assertEqual(invalid["error"]["code"], -32602)

    async def test_business_and_internal_errors_do_not_leak_internals(self):
        business = await self.connection.dispatch(
            {"jsonrpc": "2.0", "id": 3, "method": "example.fail", "params": {"value": 1}},
            tenant_id=1,
        )
        self.assertEqual(business["error"]["code"], -32000)
        self.assertEqual(business["error"]["data"]["code"], "example/failed")
        internal = await self.connection.dispatch(
            {"jsonrpc": "2.0", "id": 4, "method": "example.explode", "params": {"value": 1}},
            tenant_id=1,
        )
        self.assertEqual(internal["error"]["code"], -32603)
        self.assertNotIn("secret", str(internal))

    async def test_parse_and_envelope_errors(self):
        parse = await self.connection.dispatch_json("{", tenant_id=1)
        self.assertEqual(parse["error"]["code"], -32700)
        invalid = await self.connection.dispatch({"id": 1, "method": "x", "params": {}}, tenant_id=1)
        self.assertEqual(invalid["error"]["code"], -32600)

    async def test_cancellation_has_its_own_code(self):
        cancel = asyncio.Event()
        cancel.set()
        response = await self.connection.dispatch(
            {"jsonrpc": "2.0", "id": 5, "method": "example.echo", "params": {"value": 1}},
            tenant_id=1, cancel=cancel,
        )
        self.assertEqual(response["error"]["code"], -32800)

    async def test_batch_and_notification(self):
        batch = await self.connection.dispatch(
            [
                {"jsonrpc": "2.0", "id": 6, "method": "example.echo", "params": {"value": 1}},
                {"jsonrpc": "2.0", "method": "example.echo", "params": {"value": 2}},
            ],
            tenant_id=1,
        )
        self.assertEqual(len(batch), 1)
        self.assertEqual(batch[0]["id"], 6)
        notification = await self.connection.dispatch(
            {"jsonrpc": "2.0", "method": "example.echo", "params": {"value": 3}},
            tenant_id=1,
        )
        self.assertIsNone(notification)


if __name__ == "__main__":
    unittest.main()
