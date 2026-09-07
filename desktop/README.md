# Điều khiển máy tính cục bộ — v1

Module tùy chọn cho Windows 10/11, chạy trong phiên desktop đang đăng nhập.
Không có kết nối điều khiển từ xa, không tự khởi động cùng ứng dụng và không
thay đổi năm agent. Cài module không tự cấp quyền truy cập máy tính.

## Có thể làm gì?

- Chụp PNG của một cửa sổ đã chọn (tọa độ tính từ góc trái trên cửa sổ).
- Bấm một lần trong hình chữ nhật mục tiêu, có khoảng cách an toàn với mép.
- Nhập văn bản Unicode, gồm tiếng Việt, không đổi clipboard.
- Nhấn Enter, Tab, Backspace, Delete và các phím mũi tên.
- Cuộn 1–5 nấc mỗi thao tác ở vị trí đã chỉ định.
- Thay đổi điểm bấm, thời gian di chuột và khoảng nghỉ trong khoảng giới hạn.

Ngẫu nhiên chỉ phục vụ nhịp tương tác và tránh luôn chọn tâm nút. Có thể lặp
pixel theo xác suất; không có danh sách pixel cấm và không có cam kết tránh
phát hiện tự động hóa. Không vượt CAPTCHA, không giải quyết khóa tài khoản.
Không có vòng tự đăng bài/bình luận hàng loạt.

## Cài và thử trên Notepad trước

Từ thư mục repo, dùng Python 3.12 trên Windows:

```powershell
python -m pip install -r requirements.txt -r requirements-desktop.txt
Get-Process | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object ProcessName, MainWindowHandle, MainWindowTitle
```

Chọn handle của Notepad. Thay `123456` trong lệnh bằng số của máy bạn.
Cửa sổ phải hiện trên màn hình chính, không che khuất và nằm hoàn toàn trong
màn hình (nếu maximized có viền ngoài màn hình, hãy Restore rồi thu nhỏ).
Không chạy ứng dụng đích với quyền Administrator nếu Python không có quyền đó.

Chụp để kiểm tra tọa độ:

```powershell
python -m desktop --hwnd 123456 --observe notepad-before.png
```

Chương trình yêu cầu gõ `RUN`, sau đó có 5 giây để chuyển sang cửa sổ đích.
Ảnh lưu cục bộ, không tự gửi ra mạng. Không ghi đè ảnh đã tồn tại.

Tạo file `my-plan.json` UTF-8 với nội dung:

```json
[
  {"kind": "type", "text": "Xin chào! Đây là kiểm thử nhập tiếng Việt."}
]
```

Xem trước (không tác động desktop):

```powershell
python -m desktop --hwnd 123456 --plan my-plan.json
```

Thực thi, sau khi gõ `RUN` hãy focus vùng soạn thảo Notepad trong 5 giây:

```powershell
python -m desktop --hwnd 123456 --plan my-plan.json --execute
```

Nhấn **Esc** hoặc đưa chuột vào góc màn hình để dừng. Giữ Ctrl/Alt/Shift/Windows
cũng làm phiên dừng. Sau khi dừng cần mở phiên mới, không tự resume.

Schema các thao tác (rect = `[x, y, width, height]` theo ảnh cửa sổ):

```json
[
  {"kind": "click", "rect": [20, 80, 120, 40]},
  {"kind": "type", "text": "Nội dung"},
  {"kind": "press", "key": "enter"},
  {"kind": "scroll", "rect": [40, 120, 300, 200], "ticks": -3}
]
```

Đây chỉ là ví dụ schema, không chạy nguyên các tọa độ này trên website.
`Enter` và click có thể gửi/đăng nội dung; kiểm tra cả kế hoạch trước khi duyệt.
CLI thực thi kế hoạch tọa độ do người vận hành cung cấp; chưa có model nhìn ảnh
và tự hiểu mục tiêu ngôn ngữ tự nhiên. Nó không xác nhận một bài đã đăng thành công.

## Tích hợp vào agent

Host cục bộ đã được người dùng cho phép tạo `WindowsBackend(hwnd)`, rồi
`DesktopSession(backend)`. Đăng ký vào ToolGateway hiện có:

```python
from desktop.adapter import register_desktop
from desktop.controller import DesktopSession
from desktop.windows import WindowsBackend

session = DesktopSession(WindowsBackend(hwnd), max_actions=20, lifetime=300)
register_desktop(runtime.tool_gateway, session,
                 run_id=run_id, business_id=business_id, project_id=project_id)
```

Host phải tạo phiên khi cửa sổ đã focus. Không gọi helper này từ payload model.
Hai capability là `desktop_observe` và `desktop_act`; chỉ CMO, đúng run/business/
project, qua quyền phê duyệt có sẵn. Observe trả `observation_id` và PNG base64.
Act nhận `kind`, trường hành động tương ứng và `observation_id`.

Không tự phát hành approval token cho model. Tích hợp giao diện cần dùng luồng
phê duyệt human hiện có; không coi flag `approved=true` trong parameters là quyền.
Bản này cung cấp adapter và CLI, chưa nối nút bật/tắt hay vision planner vào UI chat.

## Ranh giới và hạn chế thực tế

- Mỗi observation chỉ dùng cho một lần thử, tối đa 15 giây; phải quan sát lại.
- Ảnh toàn cửa sổ phải còn giống trước dispatch. Video, nhấp nháy con trỏ nhập,
  nội dung động hoặc banner có thể làm thao tác bị từ chối; đây là fail-closed.
- Giới hạn mặc định 20 thao tác/5 phút, tối đa cấu hình 200 thao tác/1 giờ.
- Các khoảng nghỉ kiểm tra stop/focus mỗi tối đa 50 ms. Di chuột ngắn có kiểm tra
  trước/sau; lệnh screenshot/native bị treo không có hard process timeout.
- Không có bảo đảm nguyên tử giữa kiểm tra focus và input của Windows. Nếu focus
  đổi đúng thời điểm gửi sự kiện, input vẫn có thể tới sai cửa sổ. Không sử dụng
  cho giao dịch nhạy cảm trước khi có kiểm thử Windows và xác minh đích bổ sung.
- HWND/PID/vị trí/kích thước phải giữ nguyên. Click kiểm tra cửa sổ tại điểm bấm.
- Sau input, trả ảnh và hash mới, `input_dispatched=true`,
  `semantic_success=UNVERIFIED`. Model/người dùng phải xác minh kết quả nghiệp vụ.
- Lỗi sau dispatch có thể đã tạo tác động một phần: dừng, không retry.
- Ảnh có thể chứa dữ liệu riêng tư. Không log tự động văn bản nhập; adapter trả
  ảnh cho caller được phép. Host phải kiểm soát việc lưu/gửi ảnh tới provider.
- Không hoạt động khi Windows đang sleep/tắt máy/khóa hoặc desktop không tương tác.
- PyAutoGUI được lazy-import; CI offline và máy không có GUI không cần cài nó.

## Kiểm thử

```powershell
python -m unittest -v tests.test_local_desktop_control_v1
```

Test backend giả kiểm tra invariant, scope, approval, không retry, điểm bấm và
khoảng nghỉ. Không thay thế kiểm thử chuột/phím/Unicode/DPI thật trên Windows.
Trước dùng với website: thử Notepad, Esc, đổi cửa sổ giữa thao tác và xác nhận
không tự thử lại sau lỗi. Chưa chứng nhận live desktop trong môi trường phát triển.

## V2: quan sát bằng model thị giác và thích ứng khi bố cục thay đổi

Chạy trên nhánh `feat/desktop-visual-loop-v1`. Cần model có khả năng nhận ảnh
qua Chat Completions tương thích OpenAI. Model chỉ hỗ trợ chữ sẽ không dùng được.
Không hard-code nhà cung cấp; URL/model/key do người vận hành cấu hình riêng.
Bản này chưa dùng Settings của gateway chữ, chưa lấy DOM/UIA hoặc tự tra cứu web.

```powershell
python -m pip install -r requirements.txt -r requirements-desktop.txt
# Đặt DESKTOP_VISION_API_KEY trong môi trường cục bộ của bạn, không gửi key vào chat.
python -m desktop.visual_cli --hwnd 123456 --goal "Nhập nội dung mẫu và lưu bản nháp, không đăng" --vision-url "https://YOUR_PROVIDER/v1" --vision-model "YOUR_VISION_MODEL"
```

Lệnh trên chỉ là mẫu cấu hình, không có model hay API key mặc định.
Model local có thể dùng base URL loopback HTTP. Nhà cung cấp bên ngoài phải dùng
HTTPS. Không theo redirect, không tự fallback sang host khác, không retry model.
Người vận hành phải đồng ý việc gửi ảnh cửa sổ tới endpoint trước khi bắt đầu.
Cấu hình dùng API có thể phát sinh phí; giới hạn bước/token không phải trần tiền.

Vòng xử lý:
1. Chụp cửa sổ, gửi ảnh + mục tiêu + kết quả bước trước tới model.
2. Model trả một hành động, giải thích ngắn và dấu hiệu mong đợi sau hành động.
3. Nếu ảnh thay đổi trong lúc model suy nghĩ: bỏ tọa độ và lập lại (có giới hạn).
4. In đề xuất, yêu cầu người vận hành duyệt đúng thao tác (`YES`).
5. Sau khi focus lại cửa sổ, đối chiếu ảnh; đổi bố cục phải đề xuất/duyệt lại.
6. Thực hiện một bước rồi lấy ảnh mới cho lần đánh giá tiếp theo.

Model không được cấp quyền từ chữ trên website, không nhận được approval token.
Ảnh/website là dữ liệu không đáng tin; prompt injection vẫn là rủi ro của thị giác,
không thể loại bỏ chỉ bằng prompt. Phê duyệt độc lập từng hành động vẫn bắt buộc.
Model nói xong chỉ trả `MODEL_REPORTED_COMPLETE_UNVERIFIED`, không coi là bằng chứng
độc lập. Khi kết quả hành động bên ngoài không rõ, dừng thay vì bấm lại.

Nội dung trên 160 ký tự được chuyển thành đề xuất `paste`, được duyệt trước khi
thực thi. Dán tối đa 20.000 ký tự, hỗ trợ xuống dòng. Nhập ngắn giữ nhịp ký tự
biến thiên. Enter/click vẫn là hành động riêng. Clipboard chỉ hỗ trợ trạng thái
trống hoặc plain Unicode text; nếu có HTML/ảnh/file/custom format thì từ chối,
không xóa dữ liệu đó. Khôi phục clipboard chỉ khi sequence vẫn thuộc lần dán này;
nếu người dùng copy dữ liệu mới thì giữ nguyên dữ liệu mới.

Dán có khoảng chờ hữu hạn để ứng dụng đọc clipboard, không bảo đảm ứng dụng chậm
đã đọc xong. Cần kiểm tra nội dung thật sau dán. Clipboard history/cloud sync của
Windows có thể giữ bản sao; module không xóa lịch sử hay tắt đồng bộ. Không dùng
clipboard cho mật khẩu/bí mật. Native focus/input/clipboard không có tính nguyên tử.

Kiểm thử model giả xác minh re-plan khi nút đổi vị trí, chặn stale input, approval,
không retry và context bước trước. Native Windows test xác minh dán tiếng Việt dài
và khôi phục clipboard trong cửa sổ thử nghiệm. Khả năng hiểu giao diện của một
model thật vẫn phải được đánh giá riêng với provider của bạn; CI không gọi model trả phí.

## Live supervision v1 (opt-in, Windows)

Run from the `feat/desktop-live-supervision-v1` branch after installing
`requirements.txt` and `requirements-desktop.txt`:

```powershell
$env:DESKTOP_VISION_API_KEY = 'your-key'
python -m desktop.live_cli --hwnd 123456 --goal "Nhập và lưu bản nháp thử nghiệm" --vision-url https://your-provider.example/v1 --vision-model your-vision-model --max-steps 10 --seconds 300
```

Replace HWND and provider settings with your own. Obtain HWND as described above.
Place the target and monitor side by side on the primary display; neither may
cover the target's buttons. Click **Bắt đầu**, read the one-time grant, then focus
the target within 5 seconds. Do not run on an account containing consequential
controls until you accept the window-wide scope described below.

- Local live preview targets four PNG frames/second, with latest-frame replacement
  instead of a growing video queue. Only task observations go to the configured
  model. Preview continues during model latency; it skips captures while native
  input holds the backend lock. The viewer labels old frames with their age.
  This is a live image sequence, **not WebRTC, encoded video, or a streaming model
  video API**. No live-provider latency/accuracy benchmark has been performed.
- One task grant authorizes mouse, typing, paste and scrolling for one bound
  HWND/PID/position/size, action budget and session lifetime. There is no per-click
  prompt. The grant is created by local user consent, never model/page content.
  **It does not enforce website, account, publishing or monetary boundaries inside
  that window.** Goal text is not a permission sandbox. A model can click the wrong
  button; use an isolated test window first. Existing gateway approvals are unchanged.
- **Tạm dừng** invalidates pending plans; **Tiếp tục** provides 5 seconds to refocus
  and does not extend budget or lifetime. A pause during input may end the session
  with uncertain partial effects; it will not replay that action. Losing focus can
  pause observation or terminate execution. Esc, screen corners, Stop and closing
  the monitor stop future work. An OS input already sent cannot be recalled.
- Every step records its proposal, measured planning latency and before/after
  image hashes. Logs are bounded in memory; **Lưu nhật ký** explicitly exports JSON
  containing goal and proposed text (possibly sensitive), but not screenshots or
  API keys. No recordings are persisted automatically.
- Model completion is `MODEL_REPORTED_COMPLETE_UNVERIFIED`. A trusted application
  adapter can supply `LiveTask(..., verifier=...)` and must return
  `{'verified': True, 'evidence': 'specific structured readback evidence'}` to earn
  `HOST_VERIFIED`; the default CLI does not have this adapter. The observer verifies
  the screen did not change across verification. The GUI's **Tôi đã kiểm chứng**
  records a separate `USER_CONFIRMED` after the operator checks the real result.
- `LiveTask(session, planner, TaskGrant(...))` is reusable by the existing five-agent
  host. It is not automatically registered in chat/runtime; there is no sixth agent.
  No DOM/UIA extraction, persistent learning, generic ads-budget enforcement or
  automatic semantic verification of arbitrary websites is claimed here.

Validation: new hermetic live contracts cover stop during planning, stale screen,
pause/resume invalidation, scope mismatch, disallowed kinds, one-use task execution,
preview token isolation and independent verifier handling. The opt-in Windows smoke
uses only its own Tk window, then independently checks the native button callback.
