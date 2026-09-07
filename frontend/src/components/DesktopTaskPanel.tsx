import { useEffect, useRef, useState } from 'react';
import { apiGet, apiPost, reviewPendingApproval } from '../api/client.ts';

type Options = { windows: { hwnd: number; title: string }[]; providers: { provider_id: string; model_id: string; endpoint: string }[] };
type Proposal = { ticket: string; pending_approval_id: string; status: string };
type Snapshot = { status: string; terminal: boolean; frame: null | { png_base64: string; age_seconds: number }; events: { status: string; proposal?: { reason: string; expected: string }; steps?: number }[] };
const labels: Record<string, string> = { APPROVAL_REQUIRED: 'Chờ bạn duyệt', STARTING: 'Chuyển sang cửa sổ đích trong 5 giây', RUNNING: 'Đang thực hiện', PAUSED: 'Tạm dừng — hãy kiểm tra cửa sổ đích', RESUMING: 'Chuyển về cửa sổ đích trong 5 giây', STOPPED: 'Đã dừng', ERROR: 'Đã dừng do lỗi; kết quả có thể chưa rõ', MODEL_REPORTED_COMPLETE_UNVERIFIED: 'Model báo đã xong — cần bạn kiểm chứng', HOST_VERIFIED: 'Đã có bằng chứng kiểm chứng', STEP_LIMIT: 'Đã hết số thao tác cho phép', REPLAN_LIMIT: 'Giao diện thay đổi quá nhiều', BLOCKED: 'Cần bạn xử lý tình huống đang chặn', OUTSIDE_GRANT: 'Thao tác ngoài quyền được cấp' };

export default function DesktopTaskPanel({ chatId, initialGoal, ensureChat, onChanged }: {
  chatId: string; initialGoal: string; ensureChat: () => Promise<string>; onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<Options>({ windows: [], providers: [] });
  const [hwnd, setHwnd] = useState('');
  const [provider, setProvider] = useState('');
  const [goal, setGoal] = useState('');
  const [steps, setSteps] = useState(10);
  const [seconds, setSeconds] = useState(300);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const active = useRef<{ chat_id: string; ticket: string } | null>(null);
  const changed = useRef(onChanged); changed.current = onChanged;
  const alive = useRef(true);
  const generation = useRef(0);
  const stop = () => { const task = active.current; if (task) void apiPost('/api/desktop/stop', task).catch(() => {}); };
  useEffect(() => { alive.current = true; return () => { alive.current = false; generation.current++; stop(); }; }, []);
  useEffect(() => {
    if (active.current && active.current.chat_id !== chatId) {
      stop(); active.current = null; generation.current++; setProposal(null); setSnapshot(null);
    }
  }, [chatId]);
  useEffect(() => {
    if (!proposal) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      const task = active.current;
      if (!task || cancelled) return;
      try {
        const data = await apiGet<Snapshot>(`/api/desktop/status?chat_id=${encodeURIComponent(task.chat_id)}&ticket=${task.ticket}`);
        if (cancelled) return;
        setSnapshot(data);
        if (data.terminal) { changed.current(); return; }
      } catch { if (!cancelled) setError('Mất kết nối theo dõi. Hệ thống sẽ dừng khi quá 15 giây không nhận được tín hiệu.'); }
      if (!cancelled) timer = setTimeout(poll, 300);
    };
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [proposal]);
  const load = async () => {
    try { setOptions(await apiGet<Options>('/api/desktop/options')); setError(''); }
    catch { setError('Không lấy được cửa sổ. Tính năng cần ứng dụng Windows và dependency điều khiển máy tính.'); }
  };
  const prepare = async () => {
    if (busy) return;
    const turn = ++generation.current;
    setBusy(true); setError('');
    try {
      const cid = chatId || await ensureChat();
      const p = await apiPost<Proposal>('/api/desktop/propose', { chat_id: cid, goal, hwnd: Number(hwnd), provider_id: provider, max_steps: steps, seconds });
      if (!alive.current || turn !== generation.current) {
        void apiPost('/api/desktop/stop', { chat_id: cid, ticket: p.ticket }).catch(() => {}); return;
      }
      active.current = { chat_id: cid, ticket: p.ticket }; setProposal(p); setSnapshot(null); changed.current();
    } catch { if (alive.current) setError('Không tạo được nhiệm vụ. Kiểm tra cửa sổ, model trong Settings và giới hạn đã nhập.'); }
    finally { if (alive.current) setBusy(false); }
  };
  const approve = async () => {
    if (!proposal || !active.current || busy) return;
    setBusy(true); setError('');
    const task = { ...active.current };
    const turn = generation.current;
    try {
      const approved = await reviewPendingApproval(proposal.pending_approval_id);
      if (!alive.current || turn !== generation.current) return;
      const result = await apiPost<{ status: string }>('/api/desktop/start', { ...task, approval_token: approved.approval_token });
      if (result.status !== 'SUCCESS') throw new Error('blocked');
    } catch { if (alive.current) setError('Chưa bắt đầu. Quyền phải được duyệt qua hộp thoại native của ứng dụng desktop; không có tự động duyệt.'); }
    finally { if (alive.current) setBusy(false); }
  };
  const control = async (action: string) => {
    if (!active.current) return;
    try { await apiPost(`/api/desktop/${action}`, active.current); }
    catch { setError('Không gửi được điều khiển. Dùng Esc ở cửa sổ đích để dừng.'); }
  };
  const reset = () => { stop(); active.current = null; generation.current++; setProposal(null); setSnapshot(null); };
  const latest = snapshot?.events.filter(e => e.proposal).at(-1)?.proposal;
  return <section style={{ background: '#171717', color: '#eee', padding: '8px 16px', borderBottom: '1px solid #333' }}>
    <button onClick={() => { if (!open) { setGoal(initialGoal); void load(); } setOpen(!open); }}>Điều khiển máy tính {open ? '▴' : '▾'}</button>
    {open && <div style={{ maxHeight: '60vh', overflowY: 'auto', paddingTop: 8 }}>
      {!proposal ? <>
        <textarea aria-label="Nhiệm vụ máy tính" placeholder="Giao nhiệm vụ cho CMO…" value={goal} maxLength={8000} onChange={e => setGoal(e.target.value)} style={{ width: '100%', minHeight: 60 }} />
        <select aria-label="Cửa sổ đích" value={hwnd} onChange={e => setHwnd(e.target.value)}><option value="">Chọn cửa sổ</option>{options.windows.map(w => <option key={w.hwnd} value={w.hwnd}>{w.title}</option>)}</select>
        <button onClick={() => void load()}>Làm mới cửa sổ</button>
        <select aria-label="Model quan sát từ Settings" value={provider} onChange={e => setProvider(e.target.value)}><option value="">Model quan sát từ Settings</option>{options.providers.map(p => <option key={p.provider_id} value={p.provider_id}>{p.provider_id} / {p.model_id}</option>)}</select>
        <label> Số thao tác <input type="number" min={1} max={50} value={steps} onChange={e => setSteps(Number(e.target.value))} /></label>
        <label> Thời gian (giây) <input type="number" min={10} max={900} value={seconds} onChange={e => setSeconds(Number(e.target.value))} /></label>
        <p>Model phải hỗ trợ ảnh. API key lấy từ Settings, không cần nhập lại. Hiện hỗ trợ endpoint tương thích OpenAI.</p>
        <button disabled={busy || !goal.trim() || !hwnd || !provider} onClick={() => void prepare()}>Giao nhiệm vụ cho agent</button>
      </> : <>
        <p><strong>{labels[snapshot?.status || proposal.status] || snapshot?.status}</strong></p>
        <p>Quyền áp dụng cho toàn bộ cửa sổ đã chọn, không giới hạn được nút đăng/gửi hoặc ngân sách bên trong website. Đặt ứng dụng cạnh cửa sổ đích để theo dõi; không che cửa sổ đích.</p>
        {(snapshot?.status || proposal.status) === 'APPROVAL_REQUIRED' && <button disabled={busy} onClick={() => void approve()}>Duyệt quyền một lần và bắt đầu</button>}
        <button onClick={() => void control('pause')}>Tạm dừng</button>
        <button onClick={() => void control('resume')}>Tiếp tục sau 5 giây</button>
        <button onClick={() => void control('stop')}>DỪNG</button>
        {snapshot?.terminal && <button onClick={reset}>Nhiệm vụ mới</button>}
        {snapshot?.frame && <><p>Ảnh cách đây {snapshot.frame.age_seconds.toFixed(1)} giây{snapshot.frame.age_seconds > 1 ? ' — ảnh chưa cập nhật' : ''}</p><img alt="Màn hình cửa sổ agent đang thao tác" src={`data:image/png;base64,${snapshot.frame.png_base64}`} style={{ maxWidth: '100%', maxHeight: 360 }} /></>}
        {latest && <p>Agent đang xem xét: {latest.reason}<br />Kết quả cần kiểm tra: {latest.expected}</p>}
        <p>Kết quả và bằng chứng từng bước sẽ được trả vào cuộc trò chuyện. Khi chuyển chat hoặc mất kết nối theo dõi, tác vụ sẽ dừng.</p>
      </>}
      {error && <p role="alert" style={{ color: '#fbb' }}>{error}</p>}
    </div>}
  </section>;
}
