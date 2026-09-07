"""Chat-host integration through the existing CMO ToolGateway approval boundary."""
from __future__ import annotations
import copy
import threading
import time
import uuid
from dataclasses import asdict
from desktop.controller import Window, DesktopError
from desktop.live import LiveSession, LiveTask, TaskGrant
from desktop.vision import CompatibleVisionPlanner
from tools.adapters import BaseCapabilityAdapter, AdapterResult
from tools.capabilities import CapabilityDescriptor, CapabilityCategory, EvidenceRole, PermissionLevel, RiskLevel
from tools.receipts import ExecutionMode, ExecutionStatus
from tools.tool_gateway import ToolRequest

SCOPE_NOTICE = ('Whole-window mouse/keyboard permission. No per-click prompt. '
                'Website, account, publish buttons and ad spend inside the window are NOT sandboxed. '
                'Screenshots go to the selected endpoint. Stop cannot undo dispatched input.')
TERMINAL = {'STOPPED', 'ERROR', 'STEP_LIMIT', 'REPLAN_LIMIT', 'BLOCKED', 'OUTSIDE_GRANT',
            'MODEL_REPORTED_COMPLETE_UNVERIFIED', 'HOST_VERIFIED'}


def windows_list():
    """Read-only enumeration; does not focus windows or import input dependencies."""
    import sys
    if sys.platform != 'win32': return []
    import ctypes
    from ctypes import wintypes
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.SetProcessDPIAware()
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.IsIconic.argtypes = [wintypes.HWND]
    result = []
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        if not user.IsWindowVisible(hwnd) or user.IsIconic(hwnd): return True
        n = user.GetWindowTextLengthW(hwnd)
        if n <= 0: return True
        title = ctypes.create_unicode_buffer(min(n+1, 1024))
        user.GetWindowTextW(hwnd, title, len(title))
        rect, pid = wintypes.RECT(), wintypes.DWORD()
        if not user.GetWindowRect(hwnd, ctypes.byref(rect)): return True
        if not user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)): return True
        if rect.left < 0 or rect.top < 0 or rect.right > user.GetSystemMetrics(0) or rect.bottom > user.GetSystemMetrics(1): return True
        if rect.right-rect.left < 7 or rect.bottom-rect.top < 7: return True
        result.append({**asdict(Window(hwnd,pid.value,rect.left,rect.top,rect.right-rect.left,rect.bottom-rect.top)), 'title':title.value})
        return len(result) < 100
    user.EnumWindows.argtypes = [type(visit), wintypes.LPARAM]
    user.EnumWindows(visit, 0)
    return result


class DesktopAgentService(BaseCapabilityAdapter):
    """Only host-prepared, exact-window proposals can execute via the gateway.

    Receipts mean task accepted, not task success. Final result is appended to
    the originating conversation with evidence hashes. No extra permanent agent.
    """
    def __init__(self, gateway, chats, settings, *, windows=windows_list,
                 planner_factory=None, launch=None, clock=time.monotonic,
                 session_factory=None, countdown=5):
        self.gateway, self.chats, self.settings = gateway, chats, settings
        self.windows, self.clock = windows, clock
        self.planner_factory = planner_factory or self._planner
        self.launch = launch or (lambda target: threading.Thread(target=target, daemon=True).start())
        self.session_factory = session_factory or self._session
        self.countdown = countdown
        self._lock = threading.RLock()
        self._jobs = {}
        self._active = None
        gateway.register_adapter(self)
        gateway.registry.register_capability(CapabilityDescriptor(
            capability_id='desktop_task', name='Desktop task', description=SCOPE_NOTICE,
            category=CapabilityCategory.FILE_DATA, evidence_role=EvidenceRole.ACTION,
            input_schema={'type':'object'}, required_permissions=[PermissionLevel.EXTERNAL_WRITE],
            risk_level=RiskLevel.HIGH, human_approval_required=True, supported_agents=['cmo'],
            provider=self.adapter_name, retry_policy={'max_retries':0,'retryable_errors':[]},
            audit_policy={'log_payload':False,'redact_secrets':True,'emit_receipt':True}))

    @property
    def adapter_name(self): return 'desktop_agent'
    def execution_mode_for(self, capability_id): return ExecutionMode.REAL

    def _planner(self, provider_id):
        settings = self.settings.get_settings()
        p = settings.providers.get(provider_id)
        if not p or not p.enabled or p.adapter_type not in ('OPENAI', 'OPENAI_COMPATIBLE'):
            raise ValueError('DESKTOP_VISION_PROVIDER_UNAVAILABLE')
        if not p.default_model or not p.base_url: raise ValueError('DESKTOP_VISION_SETTINGS_REQUIRED')
        if settings.free_only_mode and getattr(p.cost_policy, 'value', p.cost_policy) != 'FREE_TIER_ALLOWED':
            raise ValueError('DESKTOP_PAID_PROVIDER_BLOCKED')
        key = self.settings._secret_store.get_secret(p.credential_ref) or ''
        planner = CompatibleVisionPlanner(p.base_url, p.default_model, key)
        return planner, {'provider_id':provider_id, 'model_id':p.default_model, 'endpoint':p.base_url}

    @staticmethod
    def _session(window, steps, seconds):
        from desktop.windows import WindowsBackend
        s = LiveSession(WindowsBackend(window.hwnd), max_actions=steps, lifetime=seconds)
        if s.window != window:
            s.stop(); raise DesktopError('DESKTOP_WINDOW_CHANGED')
        return s

    def options(self):
        providers = []
        if self.settings:
            for pid, p in self.settings.get_settings().providers.items():
                if p.enabled and p.adapter_type in ('OPENAI','OPENAI_COMPATIBLE') and p.default_model and p.base_url:
                    providers.append({'provider_id':pid,'model_id':p.default_model,'endpoint':p.base_url})
        return {'windows':self.windows(), 'providers':providers, 'scope_notice':SCOPE_NOTICE}

    def _job(self, chat_id, ticket):
        job = self._jobs.get(ticket)
        session = self.chats.get_session(chat_id)
        if not job or job['chat_id'] != chat_id or not session or session.status != 'ACTIVE':
            raise ValueError('DESKTOP_TASK_NOT_FOUND')
        return job

    def propose(self, body):
        fields = {'chat_id','goal','hwnd','provider_id','max_steps','seconds'}
        if not isinstance(body,dict) or set(body) != fields: raise ValueError('DESKTOP_PROPOSAL_INVALID')
        if any(not isinstance(body[k],str) or not body[k].strip() for k in ('chat_id','goal','provider_id')):
            raise ValueError('DESKTOP_PROPOSAL_INVALID')
        if len(body['goal']) > 8000 or type(body['hwnd']) is not int or body['hwnd'] <= 0:
            raise ValueError('DESKTOP_PROPOSAL_INVALID')
        if type(body['max_steps']) is not int or not 1 <= body['max_steps'] <= 50 or type(body['seconds']) is not int or not 10 <= body['seconds'] <= 900:
            raise ValueError('DESKTOP_LIMIT_INVALID')
        chat = self.chats.get_session(body['chat_id'])
        if not chat or chat.status != 'ACTIVE': raise ValueError('DESKTOP_CHAT_NOT_FOUND')
        candidates = [w for w in self.windows() if w['hwnd'] == body['hwnd']]
        if len(candidates) != 1: raise ValueError('DESKTOP_WINDOW_UNAVAILABLE')
        w = candidates[0]
        window = Window(**{k:w[k] for k in Window.__dataclass_fields__})
        planner, provider = self.planner_factory(body['provider_id'])
        with self._lock:
            # Bound retained goals/keys; evict finished and expired unstarted jobs.
            for ticket, old in list(self._jobs.items()):
                if ticket != self._active and (old['status'] in TERMINAL or self.clock()-old['created'] > 600):
                    del self._jobs[ticket]
            if len(self._jobs) >= 20: raise ValueError('DESKTOP_PENDING_LIMIT')
            ticket = uuid.uuid4().hex
            params = {'ticket':ticket,'goal':body['goal'],'window':asdict(window),'window_title':w['title'],
                      'max_steps':body['max_steps'],'seconds':body['seconds'],**provider,'scope_notice':SCOPE_NOTICE}
            job = {'chat_id':body['chat_id'],'params':params,'window':window,'planner':planner,
                   'business_id':chat.optional_business_id or 'LOCAL-DESKTOP',
                   'project_id':chat.optional_project_id or body['chat_id'],
                   'created':self.clock(),'status':'APPROVAL_REQUIRED','stop':threading.Event(),
                   'session':None,'task':None,'frame':None}
            self._jobs[ticket] = job
            receipt = self.gateway.execute(self._request(ticket, job))
            if receipt.status != ExecutionStatus.APPROVAL_REQUIRED:
                del self._jobs[ticket];raise ValueError('DESKTOP_PROPOSAL_BLOCKED')
            self.chats.add_user_message(body['chat_id'], body['goal'])
            self.chats.add_assistant_response(body['chat_id'], 'CMO đã chuẩn bị nhiệm vụ điều khiển máy tính. Chờ bạn duyệt quyền cho cửa sổ đã chọn.',run_id=ticket)
            return {'ticket':ticket,'pending_approval_id':receipt.approval_reference,'status':receipt.status.value,'parameters':copy.deepcopy(params)}

    def _request(self, ticket, job, token=None):
        return ToolRequest(run_id=ticket,agent_id='cmo',capability_id='desktop_task',
                           parameters=copy.deepcopy(job['params']), approval_token=token,
                           business_id=job['business_id'],project_id=job['project_id'],chat_id=job['chat_id'])

    def start(self, chat_id, ticket, token):
        with self._lock:
            job = self._job(chat_id,ticket)
            if self.clock()-job['created'] > 600: raise ValueError('DESKTOP_PROPOSAL_EXPIRED')
            receipt = self.gateway.execute(self._request(ticket,job,token))
            return {'status':receipt.status.value,'ticket':ticket,'error':receipt.error_class}

    def execute(self, capability_id, parameters, timeout_seconds=30, *, run_id='',business_id='',project_id=''):
        with self._lock:
            job = self._jobs.get(run_id)
            if not job or capability_id != 'desktop_task' or parameters != job['params'] or (business_id,project_id) != (job['business_id'],job['project_id']):
                return AdapterResult(success=False,error_code='DESKTOP_SCOPE_MISMATCH',execution_mode=ExecutionMode.REAL)
            if self._active or job['status'] != 'APPROVAL_REQUIRED' or job['stop'].is_set() or self.clock()-job['created'] > 600:
                return AdapterResult(success=False,error_code='DESKTOP_BUSY_OR_CONSUMED',execution_mode=ExecutionMode.REAL)
            current = [w for w in self.windows() if w['hwnd'] == job['window'].hwnd]
            if len(current) != 1 or any(current[0][k] != v for k,v in asdict(job['window']).items()):
                return AdapterResult(success=False,error_code='DESKTOP_WINDOW_CHANGED',execution_mode=ExecutionMode.REAL)
            self._active = run_id;job['status'] = 'STARTING';job['last_seen'] = self.clock()
            try:self.launch(lambda:self._run(run_id,job))
            except Exception:
                self._active=None;job['status']='ERROR';job['planner']=None
                return AdapterResult(success=False,error_code='DESKTOP_LAUNCH_FAILED',execution_mode=ExecutionMode.REAL)
            return AdapterResult(success=True,data={'ticket':run_id,'status':'STARTING','semantic_success':'UNVERIFIED'},execution_mode=ExecutionMode.REAL)

    def _run(self,ticket,job):
        session = None
        try:
            if job['stop'].wait(self.countdown): return
            if not self.chats.get_session(job['chat_id']): return
            p=job['params']
            session=self.session_factory(job['window'],p['max_steps'],p['seconds'])
            with self._lock:
                job['session']=session
                if job['stop'].is_set(): session.stop();return
                task=LiveTask(session,job['planner'],TaskGrant(p['goal'],job['window'],p['max_steps']))
                job['task']=task;job['status']='RUNNING'
            def preview():
                while not session._stop.is_set():
                    chat = self.chats.get_session(job['chat_id'])
                    if not chat or chat.status != 'ACTIVE' or self.clock()-job['last_seen'] > 15:
                        job['stop'].set();session.stop();break
                    if not session.paused.is_set():
                        try:
                            frame=session.preview()
                            if frame is not None: job['frame']=frame
                        except DesktopError:
                            if not session._stop.is_set():session.pause();job['status']='PAUSED'
                        except Exception:session.stop()
                    session._stop.wait(0.25)
            threading.Thread(target=preview,daemon=True).start()
            result=task.run();job['status']=result['status']
        except Exception:
            job['status']='STOPPED' if job['stop'].is_set() else 'ERROR'
        finally:
            if session: session.stop()
            if job['task'] and job['task'].last_observation:job['frame']=job['task'].last_observation
            if job['status'] not in TERMINAL:job['status']='STOPPED'
            job['planner']=None
            events=job['task'].events() if job['task'] else []
            evidence=[e for e in events if e['status']=='INPUT_DISPATCHED_UNVERIFIED']
            try:
                self.chats.add_assistant_response(job['chat_id'],
                    f"Nhiệm vụ máy tính: {job['status']}. Đã gửi {len(evidence)} thao tác. "
                    'Đây không phải xác nhận kết quả nghiệp vụ; hãy kiểm tra trạng thái thực tế trước khi gửi lại.',
                    run_id=ticket,agent_outputs={'desktop':{'status':job['status'],'evidence':evidence}})
            finally:
                with self._lock:
                    if self._active==ticket:self._active=None

    def status(self,chat_id,ticket):
        with self._lock:
            job=self._job(chat_id,ticket)
            job['last_seen']=self.clock()
            frame=copy.deepcopy(job['frame'])
            if frame:frame['age_seconds']=max(0,time.monotonic()-frame['captured_at']);frame.pop('observation_id',None)
            return {'ticket':ticket,'status':job['status'],'frame':frame,
                    'events':job['task'].events() if job['task'] else [],
                    'terminal':job['status'] in TERMINAL}

    def control(self,chat_id,ticket,action):
        with self._lock:
            job=self._job(chat_id,ticket);session=job['session']
            if action=='stop':
                job['stop'].set()
                if session:session.stop()
                if job['status']=='APPROVAL_REQUIRED':job['status']='STOPPED';job['planner']=None
            elif action=='pause' and session and job['status'] not in TERMINAL:
                session.pause();job['status']='PAUSED'
            elif action=='resume' and session and job['status']=='PAUSED' and not job['stop'].is_set():
                job['status']='RESUMING'
                def resume():
                    if not job['stop'].wait(5) and not session._stop.is_set():
                        session.resume();job['status']='RUNNING'
                threading.Thread(target=resume,daemon=True).start()
            else:raise ValueError('DESKTOP_CONTROL_INVALID')
            return {'status':job['status']}

    def shutdown(self):
        with self._lock:
            for job in self._jobs.values():
                job['stop'].set()
                if job['session']:job['session'].stop()
