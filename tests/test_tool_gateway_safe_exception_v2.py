from tools.adapters import BaseCapabilityAdapter
from tools.capabilities import CapabilityRegistry
from tools.receipts import ExecutionStatus
from tools.tool_gateway import ToolGateway, ToolRequest


class ExplodingAdapter(BaseCapabilityAdapter):
    @property
    def adapter_name(self):
        return "image_gen_adapter"

    def execute(self, capability_id, parameters, timeout_seconds=30.0, *, run_id="", business_id="", project_id=""):
        raise RuntimeError("Bearer tiny SUPER_SECRET_TOKEN=C:/private/key.txt")


def test_connector_exception_is_not_reflected_into_receipt():
    gateway = ToolGateway(capability_registry=CapabilityRegistry())
    gateway.register_adapter(ExplodingAdapter())
    receipt = gateway.execute(ToolRequest(
        run_id="RUN-SAFE-EXC",
        agent_id="creative",
        capability_id="image_generation",
        parameters={"prompt": "x"},
    ))
    assert receipt.status == ExecutionStatus.ERROR
    assert receipt.error_class == "EXECUTION_EXCEPTION"
    serialized = str(receipt.model_dump())
    assert "tiny" not in serialized
    assert "SUPER_SECRET_TOKEN" not in serialized
    assert "private/key" not in serialized
    assert receipt.error_message == "Tool execution failed inside the connector boundary."
