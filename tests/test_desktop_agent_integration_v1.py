import unittest
from dataclasses import asdict, replace
from types import SimpleNamespace
from desktop.agent import DesktopAgentService
from desktop.controller import Window
from tools.tool_gateway import ToolGateway
from tools.capabilities import CapabilityRegistry

class Chats:
    def __init__(self): self.messages=[]; self.sessions={'a':SimpleNamespace(status='ACTIVE',optional_business_id=None,optional_project_id=None)}
    def get_session(self, cid): return self.sessions.get(cid)
    def add_user_message(self,*a,**k): self.messages.append(('user',a,k))
    def add_assistant_response(self,*a,**k): self.messages.append(('assistant',a,k))

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.gateway=ToolGateway(capability_registry=CapabilityRegistry())
        self.chats=Chats(); self.work=[]; self.now=0
        self.window=Window(10,20,100,100,640,480)
        self.service=DesktopAgentService(self.gateway,self.chats,None,
            windows=lambda:[{**asdict(self.window),'title':'test'}],
            planner_factory=lambda pid: (SimpleNamespace(propose=lambda *a:None), {'provider_id':'fake','model_id':'vision','endpoint':'http://localhost/v1'}),
            launch=lambda target:self.work.append(target),clock=lambda:self.now)
    def propose(self, **kw):
        return self.service.propose({'chat_id':'a','goal':'open draft','hwnd':10,'provider_id':'fake','max_steps':3,'seconds':60,**kw})
    def approve(self,p):
        ok,record,_=self.gateway.policy_engine.approve_pending_action(p['pending_approval_id'],approved_by='test human')
        self.assertTrue(ok);return record.approval_token
    def test_proposal_does_not_start_input(self):
        p=self.propose();self.assertEqual(p['status'],'APPROVAL_REQUIRED');self.assertFalse(self.work)
    def test_start_without_approval_denied(self):
        p=self.propose();r=self.service.start('a',p['ticket'],'')
        self.assertNotEqual(r['status'],'SUCCESS');self.assertFalse(self.work)
    def test_approved_task_starts_once(self):
        p=self.propose();token=self.approve(p)
        self.assertEqual(self.service.start('a',p['ticket'],token)['status'],'SUCCESS')
        self.service.start('a',p['ticket'],token)
        self.assertEqual(len(self.work),1)
    def test_cross_chat_start_and_status_denied(self):
        p=self.propose();token=self.approve(p)
        for f in (lambda:self.service.start('b',p['ticket'],token),lambda:self.service.status('b',p['ticket'])):
            with self.assertRaises(ValueError):f()
        self.assertFalse(self.work)
    def test_changed_window_identity_denied(self):
        p=self.propose();token=self.approve(p);self.window=replace(self.window,pid=21)
        self.assertNotEqual(self.service.start('a',p['ticket'],token)['status'],'SUCCESS');self.assertFalse(self.work)
    def test_expired_proposal_denied(self):
        p=self.propose();token=self.approve(p);self.now=601
        with self.assertRaises(ValueError): self.service.start('a',p['ticket'],token)
        self.assertFalse(self.work)
    def test_unknown_fields_cannot_supply_approval_or_endpoint(self):
        for kw in ({'approved':True},{'endpoint':'https://evil.test'},{'api_key':'secret'},{'business_id':'other'}):
            with self.assertRaises(ValueError):self.propose(**kw)
        self.assertFalse(self.work)
    def test_bounds(self):
        for kw in ({'seconds':901},{'max_steps':True},{'max_steps':0},{'goal':''},{'hwnd':True}):
            with self.assertRaises(ValueError):self.propose(**kw)
    def test_missing_chat(self):
        with self.assertRaises(ValueError): self.propose(chat_id='missing')
    def test_cancelled_proposal_cannot_start(self):
        p=self.propose();token=self.approve(p);self.service.control('a',p['ticket'],'stop')
        self.assertNotEqual(self.service.start('a',p['ticket'],token)['status'],'SUCCESS');self.assertFalse(self.work)
    def test_only_one_desktop_task_at_a_time(self):
        a=self.propose();b=self.propose();ta=self.approve(a);tb=self.approve(b)
        self.service.start('a',a['ticket'],ta)
        self.assertNotEqual(self.service.start('a',b['ticket'],tb)['status'],'SUCCESS');self.assertEqual(len(self.work),1)
    def test_status_never_exposes_credentials_or_approval_tokens(self):
        p=self.propose();token=self.approve(p)
        self.service.start('a',p['ticket'],token)
        import json
        self.assertNotIn(token,json.dumps(self.service.status('a',p['ticket'])))
    def test_pending_control_cannot_resume_to_start(self):
        p=self.propose()
        with self.assertRaises(ValueError):self.service.control('a',p['ticket'],'resume')
        self.assertFalse(self.work)

if __name__=='__main__':unittest.main()

class WorkerTests(unittest.TestCase):
    setUp = IntegrationTests.setUp
    propose = IntegrationTests.propose
    approve = IntegrationTests.approve
    def make_worker(self, callback):
        from desktop.live import LiveSession
        from tests.test_local_desktop_control_v1 import FakeBackend
        self.backend=FakeBackend()
        self.service.session_factory=lambda w,n,t: LiveSession(self.backend,max_actions=n,lifetime=t)
        self.service.countdown=0
        self.service.planner_factory=lambda pid:(SimpleNamespace(propose=callback),{'provider_id':'fake','model_id':'vision','endpoint':'http://localhost/v1'})
    def test_final_result_is_returned_to_origin_chat(self):
        self.make_worker(lambda *a:{'status':'done','reason':'visible','expected':'','action':None})
        p=self.propose();self.service.start('a',p['ticket'],self.approve(p));self.work[0]()
        self.assertTrue(self.service.status('a',p['ticket'])['terminal'])
        self.assertEqual(self.chats.messages[-1][2]['agent_outputs']['desktop']['status'],'MODEL_REPORTED_COMPLETE_UNVERIFIED')
        self.assertFalse(self.backend.calls)
    def test_cancel_during_countdown_never_constructs_backend(self):
        self.service.session_factory=lambda *a:self.fail('must not construct backend')
        p=self.propose();self.service.start('a',p['ticket'],self.approve(p))
        self.service.control('a',p['ticket'],'stop');self.work[0]()
        self.assertEqual(self.service.status('a',p['ticket'])['status'],'STOPPED')
    def test_lost_viewer_stops_while_model_is_waiting(self):
        import threading
        entered,release=threading.Event(),threading.Event()
        def plan(*a):
            entered.set();release.wait(3)
            return {'status':'act','reason':'x','expected':'x','action':{'kind':'click','rect':[10,20,80,40]}}
        self.make_worker(plan)
        p=self.propose();self.service.start('a',p['ticket'],self.approve(p))
        thread=threading.Thread(target=self.work[0]);thread.start()
        try:
            self.assertTrue(entered.wait(2));self.now=16
            session=self.service._jobs[p['ticket']]['session']
            self.assertTrue(session._stop.wait(2))
        finally:release.set();thread.join(3)
        self.assertFalse(self.backend.calls)
        self.assertFalse(thread.is_alive())
    def test_deleted_chat_stops_active_task(self):
        import threading
        entered,release=threading.Event(),threading.Event()
        def plan(*a):entered.set();release.wait(3);return {'status':'done','reason':'x','expected':'','action':None}
        self.make_worker(plan)
        p=self.propose();self.service.start('a',p['ticket'],self.approve(p))
        thread=threading.Thread(target=self.work[0]);thread.start()
        try:
            self.assertTrue(entered.wait(2));del self.chats.sessions['a']
            self.assertTrue(self.service._jobs[p['ticket']]['session']._stop.wait(2))
        finally:release.set();thread.join(3)
        self.assertFalse(self.backend.calls)

class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import http.server,threading
        from app_api import server
        cls.api=server;cls.old=server.APP_BACKEND.desktop_service
        cls.fixture=IntegrationTests();cls.fixture.setUp()
        server.APP_BACKEND.desktop_service=cls.fixture.service
        cls.http=http.server.ThreadingHTTPServer(('127.0.0.1',0),server.DepartmentAPIHandler)
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close();cls.thread.join(2)
        cls.api.APP_BACKEND.desktop_service=cls.old
    def request(self,path,body=None,auth=True):
        import urllib.request,urllib.error,json
        headers={'Content-Type':'application/json'}
        if auth:headers['Authorization']='Bearer '+self.api.GLOBAL_API_SESSION_TOKEN
        req=urllib.request.Request(f'http://127.0.0.1:{self.http.server_port}'+path,
                                   data=json.dumps(body).encode() if body is not None else None,headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=3) as r:return r.status,json.loads(r.read())
        except urllib.error.HTTPError as r:return r.code,json.loads(r.read())
    def test_noauth_options_and_control_are_denied(self):
        before = len(self.fixture.work)
        for path,body in [('/api/desktop/options',None),('/api/desktop/propose',{}),('/api/desktop/start',{}),('/api/desktop/stop',{})]:
            self.assertEqual(self.request(path,body,False)[0],401)
        self.assertEqual(len(self.fixture.work), before)
    def test_http_proposal_status_and_approved_start(self):
        code,p=self.request('/api/desktop/propose',{'chat_id':'a','goal':'draft','hwnd':10,'provider_id':'fake','max_steps':2,'seconds':60})
        self.assertEqual(code,200)
        path='/api/desktop/status?chat_id=a&ticket='+p['ticket']
        self.assertEqual(self.request(path)[1]['status'],'APPROVAL_REQUIRED')
        self.assertEqual(self.request(path+'&chat_id=b')[0],400)
        self.assertEqual(self.request(path.replace('chat_id=a','chat_id=b'))[0],400)
        self.assertNotEqual(self.request('/api/desktop/start',{'chat_id':'a','ticket':p['ticket'],'approval_token':'fake'})[1]['status'],'SUCCESS')
        token=self.fixture.approve(p)
        self.assertEqual(self.request('/api/desktop/start',{'chat_id':'a','ticket':p['ticket'],'approval_token':token})[1]['status'],'SUCCESS')
        self.assertEqual(self.request('/api/desktop/stop',{'chat_id':'a','ticket':p['ticket']})[0],200)
    def test_unknown_route_and_tampered_control_rejected(self):
        self.assertEqual(self.request('/api/desktop/execute_anything',{})[0],404)
        self.assertEqual(self.request('/api/desktop/start',{'approved':True})[0],400)

class SettingsTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import Mock
        self.provider=SimpleNamespace(enabled=True,adapter_type='OPENAI_COMPATIBLE',default_model='vision',
                                      base_url='http://127.0.0.1:12345/v1',credential_ref='ref',cost_policy='FREE_TIER_ALLOWED')
        self.current=SimpleNamespace(providers={'local':self.provider},free_only_mode=True)
        self.settings=SimpleNamespace(get_settings=lambda:self.current,_secret_store=SimpleNamespace(get_secret=Mock(return_value='test-only-secret')))
        self.service=DesktopAgentService(ToolGateway(capability_registry=CapabilityRegistry()),Chats(),self.settings,windows=lambda:[])
    def test_provider_and_credential_pinned_before_settings_change(self):
        planner,meta=self.service._planner('local')
        self.provider.base_url='http://127.0.0.1:9999/v1';self.provider.default_model='different'
        self.assertEqual(planner.url,'http://127.0.0.1:12345/v1/chat/completions')
        self.assertEqual(planner.model,'vision')
        self.assertNotIn('test-only-secret',str(meta))
    def test_disabled_or_native_only_provider_rejected(self):
        self.provider.enabled=False
        with self.assertRaises(ValueError):self.service._planner('local')
        self.provider.enabled=True;self.provider.adapter_type='GEMINI_NATIVE'
        with self.assertRaises(ValueError):self.service._planner('local')
    def test_free_only_blocks_paid_provider(self):
        self.provider.cost_policy='PAID'
        with self.assertRaises(ValueError):self.service._planner('local')
        self.settings._secret_store.get_secret.assert_not_called()
    def test_remote_http_rejected_without_request(self):
        self.provider.base_url='http://remote.example/v1'
        with self.assertRaises(RuntimeError):self.service._planner('local')

    def test_builtin_paid_cost_authority_cannot_be_overridden_by_stale_settings(self):
        self.current.providers['openai'] = self.provider
        with self.assertRaises(ValueError): self.service._planner('openai')
        self.settings._secret_store.get_secret.assert_not_called()
