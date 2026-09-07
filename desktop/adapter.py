"""Explicit host-side registration into the existing governed ToolGateway."""
from desktop.controller import DesktopError, DesktopSession
from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.capabilities import CapabilityCategory, CapabilityDescriptor, EvidenceRole, PermissionLevel, RiskLevel
from tools.receipts import ExecutionMode


def action_schema():
    """Expose executable arguments to tool-calling models without host authority."""
    rect = {'type': 'array', 'items': {'type': 'integer'}, 'minItems': 4, 'maxItems': 4,
            'description': 'Window-relative [x,y,width,height], from the latest screenshot; minimum size 7x7.'}
    payloads = {
        'click': {'rect': rect},
        'type': {'text': {'type': 'string', 'minLength': 1, 'maxLength': 500,
                          'description': 'Printable Unicode only; Enter requires a separate approved action.'}},
        'paste': {'text': {'type': 'string', 'minLength': 1, 'maxLength': 20000,
                           'description': 'Long Unicode text; clipboard preservation required.'}},
        'press': {'key': {'enum': ['enter', 'tab', 'backspace', 'left', 'right', 'up', 'down', 'delete']}},
        'scroll': {'rect': rect, 'ticks': {'type': 'integer', 'minimum': -5, 'maximum': 5,
                                          'description': 'Nonzero; positive up, negative down.'}},
    }
    return {'oneOf': [
        {'type': 'object', 'properties': {
            'kind': {'const': kind}, 'observation_id': {'type': 'string'}, **fields},
         'required': ['kind', 'observation_id', *fields], 'additionalProperties': False}
        for kind, fields in payloads.items()
    ]}


class DesktopAdapter(BaseCapabilityAdapter):
    def __init__(self, session: DesktopSession, *, run_id: str, business_id: str, project_id: str):
        if not all(isinstance(v, str) and v.strip() for v in (run_id, business_id, project_id)):
            raise ValueError('An explicit run/business/project scope is required')
        self.session = session
        self._scope = (run_id, business_id, project_id)

    @property
    def adapter_name(self):
        return 'local_desktop'

    def execution_mode_for(self, capability_id):
        return ExecutionMode.REAL

    def execute(self, capability_id, parameters, timeout_seconds=30.0, *, run_id='', business_id='', project_id=''):
        if (run_id, business_id, project_id) != self._scope:
            return AdapterResult(success=False, error_code='DESKTOP_SCOPE_MISMATCH', execution_mode=ExecutionMode.REAL)
        try:
            if capability_id == 'desktop_observe' and parameters == {}:
                result = self.session.observe()
            elif capability_id == 'desktop_act':
                result = self.session.act(parameters, timeout_seconds=timeout_seconds)
            else:
                raise DesktopError('DESKTOP_CAPABILITY_OR_PARAMETERS_INVALID')
            return AdapterResult(success=True, data=result, execution_mode=ExecutionMode.REAL)
        except DesktopError as exc:
            return AdapterResult(success=False, error_code=str(exc), error_message=str(exc), execution_mode=ExecutionMode.REAL)
        except Exception:
            self.session.stop()
            return AdapterResult(success=False, error_code='DESKTOP_BACKEND_ERROR_STOPPED', execution_mode=ExecutionMode.REAL)


def register_desktop(gateway, session, *, run_id, business_id, project_id):
    """Trusted local host only. Does not open a network listener or grant approval.

    All desktop input, including Enter/scroll, requires existing human approval
    because its effect cannot be inferred safely from a coordinate or key name.
    Screenshots require approval too; they may contain private information.
    """
    for cid in ('desktop_observe', 'desktop_act'):
        if gateway.registry.get_capability(cid) is not None:
            raise ValueError('Desktop capabilities already registered')
    if gateway.get_adapter('local_desktop') is not None:
        raise ValueError('Desktop adapter already registered')
    adapter = DesktopAdapter(session, run_id=run_id, business_id=business_id, project_id=project_id)
    gateway.register_adapter(adapter)
    for cid in ('desktop_observe', 'desktop_act'):
        gateway.registry.register_capability(CapabilityDescriptor(
            capability_id=cid, name=cid, description=(
                'Observe the explicitly bound local window; coordinates are window-relative.' if cid == 'desktop_observe'
                else 'Dispatch one approved click/type/press/scroll using a fresh observation. No automatic retries.'),
            category=CapabilityCategory.FILE_DATA,
            evidence_role=EvidenceRole.OBSERVATION if cid == 'desktop_observe' else EvidenceRole.ACTION,
            input_schema=({'type': 'object', 'properties': {}, 'additionalProperties': False}
                          if cid == 'desktop_observe' else action_schema()),
            required_permissions=[PermissionLevel.EXTERNAL_WRITE],
            risk_level=RiskLevel.HIGH, human_approval_required=True,
            supported_agents=['cmo'], provider=adapter.adapter_name,
            retry_policy={'max_retries': 0, 'retryable_errors': []},
            audit_policy={'log_payload': False, 'redact_secrets': True, 'emit_receipt': True},
        ))
    return adapter
