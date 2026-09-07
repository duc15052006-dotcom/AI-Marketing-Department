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
