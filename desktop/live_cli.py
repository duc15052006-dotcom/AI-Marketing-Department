"""Local Windows live monitor. No HTTP listener and no remote control port."""
from __future__ import annotations
import argparse
import base64
import io
import json
import os
import threading
import time


def main():
    parser = argparse.ArgumentParser(description='Live screen supervision and one-time window input grant')
    parser.add_argument('--hwnd', required=True, type=lambda s: int(s, 0))
    parser.add_argument('--goal', required=True)
    parser.add_argument('--vision-url', required=True)
    parser.add_argument('--vision-model', required=True)
    parser.add_argument('--max-steps', type=int, default=10)
    parser.add_argument('--seconds', type=int, default=300)
    args = parser.parse_args()
    if not 1 <= args.max_steps <= 50 or not 10 <= args.seconds <= 900:
        parser.error('max-steps: 1..50; seconds: 10..900')
    if not 1 <= len(args.goal.strip()) <= 8000: parser.error('Invalid goal')
    import tkinter as tk
    from tkinter import messagebox, filedialog
    from PIL import Image, ImageTk
    from desktop.controller import DesktopError
    from desktop.windows import WindowsBackend
    from desktop.vision import CompatibleVisionPlanner
    from desktop.live import LiveSession, LiveTask, TaskGrant
    planner = CompatibleVisionPlanner(args.vision_url, args.vision_model,
                                      os.environ.get('DESKTOP_VISION_API_KEY', ''))
    root = tk.Tk()
    root.title('Agent — Quan sát live')
    root.geometry('780x820')
    state = {'session': None, 'task': None, 'frame': None, 'terminal': False,
             'closing': False, 'starting': False, 'message': 'Chưa cấp quyền', 'user_confirmed': False}
    status = tk.StringVar(value=state['message'])
    tk.Label(root, text=args.goal, wraplength=740, justify='left').pack(fill='x', padx=10, pady=5)
    tk.Label(root, textvariable=status, wraplength=740, fg='#135f91').pack(fill='x')
    preview = tk.Label(root, text='Màn hình sẽ xuất hiện sau khi bắt đầu', width=90, height=25)
    preview.pack(fill='both', expand=True, padx=8, pady=5)
    activity = tk.Text(root, height=9, wrap='word', state='disabled')
    activity.pack(fill='x', padx=8)
    controls = tk.Frame(root)
    controls.pack(fill='x', pady=8)

    def stop():
        state['starting'] = False
        if state['session']: state['session'].stop()
        state['message'] = 'Đã yêu cầu dừng — thao tác đang gửi có thể đã có hiệu lực'

    def pause():
        if state['session'] and not state['terminal']:
            state['session'].pause()
            state['message'] = 'Tạm dừng. Kế hoạch đang chờ sẽ bị bỏ.'

    def resume():
        session = state['session']
        if not session or state['terminal'] or session._stop.is_set(): return
        state['message'] = 'Trong 5 giây: chuyển về đúng cửa sổ đích để tiếp tục'
        def ready():
            if not state['closing'] and not state['terminal']:
                session.resume()
                state['message'] = 'Đang chạy'
        root.after(5000, ready)

    def observe():
        session = state['session']
        while not session._stop.is_set() and not state['closing']:
            if not session.paused.is_set():
                try:
                    frame = session.preview()
                    if frame is not None: state['frame'] = frame
                except DesktopError:
                    if not session._stop.is_set():
                        session.pause()
                        state['message'] = 'Đã tạm dừng: kiểm tra cửa sổ đích/focus; bấm Tiếp tục để quan sát lại'
                except Exception:
                    session.stop()
                    state['message'] = 'Dừng: không lấy được màn hình'
            session._stop.wait(0.25)

    def run_task():
        try:
            result = state['task'].run()
            state['message'] = result['status']
        except Exception:
            state['message'] = 'Đã dừng do lỗi, mất focus hoặc thao tác chưa rõ kết quả. Không tự thử lại.'
        finally:
            if state['task'].last_observation:
                state['frame'] = state['task'].last_observation
            state['terminal'] = True

    def launch():
        if state['closing'] or not state['starting']: return
        try:
            session = LiveSession(WindowsBackend(args.hwnd), max_actions=args.max_steps, lifetime=args.seconds)
            grant = TaskGrant(args.goal, session.window, args.max_steps)
            task = LiveTask(session, planner, grant)
            state.update(session=session, task=task, starting=False, message='Đang chạy')
            threading.Thread(target=observe, daemon=True).start()
            threading.Thread(target=run_task, daemon=True).start()
        except Exception:
            state.update(starting=False, terminal=True, message='Không khởi động được: kiểm tra HWND, focus và dependency Windows')

    def start():
        if state['starting'] or state['session'] or state['terminal']: return
        consent = (f'Mục tiêu: {args.goal}\n\nCửa sổ HWND: {args.hwnd}\n'
                   f'Tối đa {args.max_steps} thao tác trong {args.seconds} giây.\n'
                   f'Ảnh màn hình và nội dung nhiệm vụ được gửi đến: {args.vision_url}\n\n'
                   'Bạn cấp quyền bấm, nhập, dán và cuộn trong TOÀN BỘ cửa sổ này, không hỏi từng bước. '
                   'Quyền này KHÔNG giới hạn được website, tài khoản hoặc ngân sách bên trong cửa sổ. '
                   'Model có thể nhấp nhầm nút đăng/gửi/mua. Hãy thử trên cửa sổ thử nghiệm trước.\n\n'
                   'Esc hoặc góc màn hình: dừng. Đặt bảng theo dõi cạnh cửa sổ đích, không che nó. '
                   'Mất focus sẽ tạm dừng hoặc kết thúc; không tự giành lại chuột.\n\nCấp quyền cho phiên này?')
        if not messagebox.askyesno('Cấp quyền một lần cho nhiệm vụ', consent): return
        state.update(starting=True, message='Trong 5 giây: đưa cửa sổ đích lên trước; giữ bảng theo dõi bên cạnh')
        root.after(5000, launch)

    def confirm():
        if not state['terminal'] or not state['task']: return
        if messagebox.askyesno('Kiểm chứng bởi bạn', 'Bạn đã tự kiểm tra kết quả thực tế của nhiệm vụ, ngoài tuyên bố của model?'):
            state['task'].emit('USER_CONFIRMED', goal=args.goal)
            state['user_confirmed'] = True
            state['message'] = 'Bạn đã xác nhận kết quả — USER_CONFIRMED'

    def export():
        if not state['task']: return
        pause()
        path = filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('JSON', '*.json')])
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump({'goal': args.goal, 'events': state['task'].events(),
                               'user_confirmed': state['user_confirmed'],
                               'note': 'Input dispatched is not semantic success. No screenshots stored in this report.'},
                              f, ensure_ascii=False, indent=2)
            except OSError: messagebox.showerror('Lỗi', 'Không lưu được nhật ký')

    for title, callback in [('Bắt đầu', start), ('Tạm dừng', pause), ('Tiếp tục (5s)', resume),
                            ('DỪNG', stop), ('Tôi đã kiểm chứng', confirm), ('Lưu nhật ký', export)]:
        tk.Button(controls, text=title, command=callback).pack(side='left', padx=3)
    tk.Label(root, text='Live dạng chuỗi khung hình, mục tiêu 4 fps; có thể đứng hình khi đang nhập. '
             'Phân tích model theo từng bước, chưa phải streaming video API.', wraplength=740).pack()
    last_frame, last_events = None, None
    def refresh():
        nonlocal last_frame, last_events
        if state['closing']: return
        frame = state['frame']
        age = time.monotonic() - frame['captured_at'] if frame else None
        suffix = f' | Ảnh cách đây {age:.1f}s' if age is not None else ''
        if age is not None and age > 1: suffix += ' — KHÔNG PHẢI ẢNH HIỆN TẠI'
        status.set(state['message'] + suffix)
        if frame and frame is not last_frame:
            try:
                picture = Image.open(io.BytesIO(base64.b64decode(frame['png_base64'])))
                picture.thumbnail((740, 440))
                photo = ImageTk.PhotoImage(picture)
                preview.configure(image=photo, text='', width=740, height=440)
                preview.image = photo
                last_frame = frame
            except Exception:
                stop()
                state['message'] = 'Dừng: không hiển thị được màn hình'
        task = state['task']
        if task:
            events = task.events()
            rendered = json.dumps(events[-8:], ensure_ascii=False, indent=2)
            if rendered != last_events:
                activity.configure(state='normal'); activity.delete('1.0', 'end')
                activity.insert('end', rendered); activity.see('end'); activity.configure(state='disabled')
                last_events = rendered
        root.after(100, refresh)

    def close():
        state['closing'] = True
        stop()
        root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    root.bind('<Escape>', lambda e: stop())
    refresh()
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
