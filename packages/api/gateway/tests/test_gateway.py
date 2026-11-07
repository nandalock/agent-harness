import asyncio
import unittest

from pydantic import BaseModel

from agent_platform_rpc_gateway import (
    RpcContext,
    RpcError,
    RpcGateway,
    RpcInvalidParams,
    RpcMethodContract,
    RpcMethodNotFound,
)


class Params(BaseModel):
    value: int


class Result(BaseModel):
    doubled: int


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.gateway = RpcGateway()

        async def double(params: Params, context: RpcContext):
            return Result(doubled=params.value * 2)

        self.registration = self.gateway.register(
            RpcMethodContract("example.double", Params, Result), double,
        )

    async def asyncTearDown(self):
        await self.registration.aclose()

    async def test_validates_and_returns_registered_contract(self):
        result = await self.gateway.invoke(
            "example.double", {"value": 4}, RpcContext(tenant_id=1),
        )
        self.assertEqual(result, {"doubled": 8})

    async def test_unknown_method_is_not_reflected(self):
        with self.assertRaises(RpcMethodNotFound):
            await self.gateway.invoke("service.secret", {}, RpcContext(tenant_id=1))

    async def test_invalid_params_are_rejected(self):
        with self.assertRaises(RpcInvalidParams):
            await self.gateway.invoke(
                "example.double", {"value": "not-an-int"}, RpcContext(tenant_id=1),
            )

    async def test_business_error_keeps_stable_code(self):
        async def fail(params: Params, context: RpcContext):
            raise RpcError("example/not-found", "missing", {"id": 7})

        registration = self.gateway.register(
            RpcMethodContract("example.fail", Params, Result), fail,
        )
        try:
            with self.assertRaises(RpcError) as caught:
                await self.gateway.invoke("example.fail", {"value": 1}, RpcContext(tenant_id=1))
            self.assertEqual(caught.exception.code, "example/not-found")
            self.assertEqual(caught.exception.details, {"id": 7})
        finally:
            await registration.aclose()

    async def test_unregister_removes_only_its_own_method(self):
        await self.registration.aclose()
        with self.assertRaises(RpcMethodNotFound):
            await self.gateway.invoke("example.double", {"value": 1}, RpcContext(tenant_id=1))


if __name__ == "__main__":
    unittest.main()
