# AI Marketing Department

> A local-first, AI-assisted multi-agent marketing system built around five permanent specialist agents: **CMO, Intelligence, Strategist, Creative, and Performance**.
>
> **I am learning by building.**

---

## 🇻🇳 Giới thiệu

**AI Marketing Department** là dự án cá nhân của tôi nhằm thử nghiệm cách tổ chức một “phòng Marketing bằng AI” theo mô hình nhiều agent có vai trò rõ ràng, phối hợp với nhau qua workflow, dữ liệu, evidence, memory và các lớp kiểm soát.

Thay vì để một chatbot duy nhất làm mọi việc, dự án chia công việc thành **5 agent cố định**:

- **CMO** — điều phối, quản trị chiến lược và phê duyệt.
- **Intelligence** — nghiên cứu thị trường, khách hàng, sản phẩm và đối thủ.
- **Strategist** — định vị, chiến lược, GTM và thiết kế thử nghiệm.
- **Creative** — concept, copy, kịch bản, storyboard và định hướng sản xuất nội dung.
- **Performance** — đo lường, tracking, KPI, media planning và tối ưu hiệu suất.

Dự án được xây theo hướng **local-first**, ưu tiên khả năng kiểm soát dữ liệu, provider/model có thể thay đổi, bằng chứng có provenance, và các hành động quan trọng vẫn cần **Human Approval**.

> **Lưu ý:** dự án vẫn đang được phát triển và hardening. Một số tài liệu trong repo là lịch sử nghiên cứu/đánh giá của từng giai đoạn và không nên được hiểu là cam kết rằng mọi tính năng đã hoàn thiện ở trạng thái production.

---

## 🇬🇧 About the project

**AI Marketing Department** is my personal project exploring how a structured AI marketing department can be built with multiple specialized agents instead of one general-purpose assistant.

The system has **exactly five permanent logical agents**:

1. **CMO** — orchestration, governance, review, and final decision support.
2. **Intelligence** — market, product, competitor, and customer research.
3. **Strategist** — positioning, go-to-market strategy, growth planning, and experiments.
4. **Creative** — concepts, copy, scripts, storyboards, and creative production planning.
5. **Performance** — measurement, analytics, KPI design, media planning, and optimization.

The project is designed around a **local-first application**, provider-agnostic model routing, evidence-aware workflows, scoped memory/knowledge, and human approval for consequential actions.

This repository is an active work in progress. Historical benchmark and evaluation files should be interpreted only in the context of the commit and environment that produced them.

---

## Mục tiêu của dự án

Tôi bắt đầu dự án này với một mục tiêu khá thực tế: **giảm thời gian cho các công việc Marketing lặp lại nhưng vẫn giữ được cấu trúc, khả năng kiểm tra và quyền kiểm soát của con người**.

Các mục tiêu chính:

- Tách công việc Marketing thành các vai trò chuyên môn rõ ràng.
- Cho các agent trao đổi thông tin theo workflow thay vì hoạt động rời rạc.
- Hạn chế việc model tự bịa dữ liệu hoặc nâng mức chắc chắn của một claim không có bằng chứng.
- Cho phép thay provider/model mà không phải viết lại logic của từng agent.
- Lưu knowledge và memory theo scope để hạn chế lẫn dữ liệu giữa business/project/session.
- Giữ Human-in-the-Loop cho các hành động có ảnh hưởng thật như publishing, external writes hoặc ngân sách.
- Xây một nền tảng có thể tiếp tục mở rộng thêm skills, tools, plugins và providers trong tương lai.

---

## Kiến trúc tổng quan

```text
                         Human / User
                              │
                              ▼
                    ┌──────────────────┐
                    │       CMO        │
                    │   Orchestrator   │
                    └────────┬─────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
          ▼                  ▼                  ▼
 ┌────────────────┐ ┌────────────────┐ ┌────────────────┐
 │  INTELLIGENCE  │ │   STRATEGIST   │ │    CREATIVE    │
 │ Research       │ │ Strategy / GTM │ │ Content / Idea │
 └────────┬───────┘ └────────┬───────┘ └────────┬───────┘
          │                  │                  │
          └──────────────────┼──────────────────┘
                             ▼
                    ┌──────────────────┐
                    │   PERFORMANCE    │
                    │ Analytics / Ops  │
                    └────────┬─────────┘
                             │
                             ▼
                    Human Approval Gate
```

### Các lớp chính

```text
Frontend
  └─ React + TypeScript + Vite

Desktop Shell
  └─ Tauri v2 / Rust

Local Backend
  └─ Python
      ├─ Chat / Runtime
      ├─ Five-Agent orchestration
      ├─ Knowledge & Memory
      ├─ Evidence / Provenance
      ├─ Tool Gateway
      ├─ Provider Registry
      └─ Universal Model Gateway
```

---

## Provider & Model architecture

Một nguyên tắc quan trọng của dự án là **không hard-code model provider vào 5 agent**.

```text
Agent
  │
  ▼
Universal Model Gateway
  │
  ├─ Provider Registry
  ├─ Model Policy
  ├─ Global provider/model
  ├─ Per-agent overrides
  ├─ Fallback chain
  └─ Run-pinned provider snapshot
```

Thiết kế này giúp hệ thống có thể:

- đổi model/provider từ phần Settings;
- dùng một provider chung cho cả hệ thống;
- override provider/model cho từng agent;
- cấu hình fallback;
- hỗ trợ provider OpenAI-compatible tùy chỉnh;
- giữ lựa chọn provider ổn định trong suốt một run;
- tránh để credential xuất hiện trong response công khai hoặc log không an toàn.

---

## Evidence, Knowledge & Memory

Dự án cố gắng phân biệt rõ giữa **thông tin có bằng chứng** và **suy luận của model**.

Một số nguyên tắc đang được áp dụng trong codebase:

- evidence có provenance/source;
- dữ liệu từ external source không tự động trở thành “verified fact”;
- candidate memory không tự động được coi là verified memory;
- tool failure không được biến thành positive evidence;
- scope được dùng để hạn chế cross-session / cross-business / cross-project leakage;
- secret/token được redaction trước khi đi vào nhiều loại receipt/event công khai.

---

## Tooling hiện có

Codebase hiện có các lớp tool/observation phục vụ nghiên cứu và thu thập dữ liệu, bao gồm các hướng như:

- đọc nội dung web;
- phân tích URL;
- web search;
- đọc public discussion;
- YouTube metadata / transcript;
- file handling;
- evidence building;
- tool execution receipt và provenance.

Các tool có thể thay đổi theo quá trình hardening, vì vậy code và test tại commit hiện tại luôn là nguồn đáng tin cậy hơn tài liệu cũ.

---

## Giao diện ứng dụng

Ứng dụng hiện có frontend bằng **React + TypeScript + Vite**, backend local bằng **Python**, cùng desktop shell **Tauri/Rust**.

Mục tiêu UI là giữ trải nghiệm giống một AI workspace đơn giản: chat trước, các cấu hình nâng cao nằm trong Settings, và người dùng có thể quản lý model/provider mà không sửa code agent.

---

## Quick start — Windows

### 1. Yêu cầu

Bạn cần cài:

- Git
- Python 3
- Node.js + npm
- PowerShell

Python 3.12 là phiên bản đang được dùng trong workflow regression chính của repo.

### 2. Clone repository

```powershell
git clone https://github.com/duc15052006-dotcom/AI-Marketing-Department.git
cd AI-Marketing-Department
```

### 3. Tạo Python virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Nếu PowerShell chặn script trong session hiện tại:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 4. Cài Python dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 5. Cài frontend dependencies

```powershell
npm --prefix frontend install
```

### 6. Chạy local app

```powershell
.\run_app.ps1
```

Launcher sẽ khởi động local Python API, Vite frontend và mở giao diện local trên máy.

Dừng bằng:

```text
Ctrl + C
```

---

## Cấu hình API / Model Provider

Repository **không được thiết kế để đi kèm API key cá nhân của tác giả**.

Sau khi chạy app:

1. Mở **Settings**.
2. Chọn hoặc tạo provider.
3. Nhập API key của bạn.
4. Chọn model.
5. Test connection.
6. Save cấu hình.

Credential nên được lưu ở local secure storage / environment phù hợp và **không commit vào Git**.

Các file như `.env`, private key, database runtime và log local đã được đưa vào `.gitignore`.

---

## Chạy test

### Python unittest

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

### Frontend tests

```powershell
npm --prefix frontend test
```

### Frontend build

```powershell
npm --prefix frontend run build
```

Repository cũng có GitHub Actions workflow cho offline regression trên Windows/Python 3.12.

---

## Cấu trúc repository

```text
AI-Marketing-Department/
├─ .agents/              # Agent definitions / DNA
├─ app_api/              # Local application API
├─ chat/                 # Chat session, routing, persistence
├─ config/               # Configuration authority
├─ connectors/           # External connector abstractions
├─ creative_engine/      # Creative production structure
├─ evaluations/          # Evaluation & benchmark evidence
├─ frontend/             # React / TypeScript UI
├─ governance/           # Safety, claim and approval governance
├─ integrations/models/  # Model adapters, gateway, registry, settings
├─ knowledge/            # Knowledge system
├─ memory/               # Memory system
├─ runtime/              # Five-agent runtime / orchestration
├─ schemas/              # Typed domain contracts
├─ src-tauri/            # Tauri desktop shell
├─ tests/                # Regression / adversarial tests
├─ tools/                # Tool gateway & observation backends
├─ workspace/            # Business / project workspace scope
└─ run_app.ps1           # Local Windows launcher
```

---

## Trạng thái dự án

**Status: Active Development / Hardening**

Dự án đã có lượng code và test đáng kể, nhưng tôi vẫn đang tiếp tục:

- hardening kiến trúc;
- sửa regression;
- cải thiện agent intelligence;
- cải thiện memory/knowledge;
- hoàn thiện provider interoperability;
- cải thiện UI/UX;
- thêm skills/plugins;
- cải thiện khả năng research thực tế;
- đánh giá lại chất lượng multi-agent bằng benchmark công bằng hơn.

Tôi cố gắng không dùng README để tuyên bố một tính năng “hoàn thành” nếu code/test hiện tại chưa chứng minh điều đó.

---

# About Me

## Nguyễn Văn Đức

**Digital Marketing Student · AI-assisted Builder · Project Initiator**

Tôi là **Nguyễn Văn Đức**, 20 tuổi, hiện đang học **Digital Marketing tại FPT Polytechnic**.

Tôi **không có nền tảng lập trình chuyên nghiệp**. Phần lớn quá trình triển khai và chỉnh sửa code của dự án được thực hiện với sự hỗ trợ của các công cụ AI như ChatGPT và các coding assistants.

Vai trò chính của tôi trong dự án là:

- hình thành ý tưởng sản phẩm;
- thiết kế workflow Marketing;
- xác định agent nào nên chịu trách nhiệm cho từng loại công việc;
- thử nghiệm hệ thống;
- tìm lỗi và regression;
- đánh giá output;
- đưa ra yêu cầu hardening;
- định hướng sản phẩm và trải nghiệm người dùng;
- tiếp tục học cách xây dựng AI Agent thông qua chính dự án này.

Tôi muốn nói rõ điều này vì tôi không muốn tự nhận mình là một software engineer khi chưa có nền tảng tương ứng. Đây là một dự án **AI-assisted**, nhưng những quyết định về ý tưởng, workflow, yêu cầu sản phẩm, test thực tế và quá trình lặp lại vẫn là phần công việc tôi trực tiếp theo đuổi.

> **I am learning by building.**

### English

My name is **Nguyen Van Duc**. I am a 20-year-old **Digital Marketing student at FPT Polytechnic**.

I do not come from a traditional software engineering background. Much of the implementation work in this repository has been created and refined with the help of AI coding tools. My focus is on the product idea, marketing workflows, agent responsibilities, testing, reviewing failures, defining hardening requirements, and continuously improving the system.

I see this project as a way to learn AI agents by actually building one.

### Contact

- Email: **duc15052006@gmail.com**
- GitHub: **@duc15052006-dotcom**

---

## AI-assisted development disclosure

This repository is developed with substantial assistance from AI tools.

AI has been used for tasks such as:

- generating implementation drafts;
- reviewing code;
- proposing tests;
- debugging;
- architecture discussions;
- refactoring suggestions;
- documentation support.

AI-generated code is not assumed to be correct automatically. The repository is continuously reviewed through tests, regressions, runtime checks, and manual validation.

---

## Security

Please **do not commit**:

- API keys;
- access tokens;
- private certificates;
- `.env` files containing credentials;
- local databases containing user data;
- runtime logs containing sensitive information.

If you discover a security issue, avoid publishing real credentials in an issue or PR.

---

## Contributing

The project is currently driven primarily by my own learning and development process, but issues, technical feedback, architecture reviews, and focused pull requests are welcome.

When contributing:

1. Keep patches small and reviewable.
2. Prefer one problem per branch/PR.
3. Add regression coverage when fixing a bug.
4. Do not weaken existing security/governance tests to make a test pass.
5. Distinguish verified behavior from assumptions or planned features.

---

## Documentation hierarchy

When repository documents disagree, use this order:

1. **Current code and automated tests**
2. `STATUS_MATRIX.md`
3. `ARCHITECTURE.md` and `AGENT_PROTOCOL.md`
4. Commit-specific evaluation/certification artifacts
5. Historical planning/gap documents

See `SOURCE_OF_TRUTH.md` for the full rule set.

---

## License

No open-source license has been selected for this repository yet.

Until a license is added, please do not assume that public visibility automatically grants permission to copy, redistribute, or commercially reuse the source code.

---

## Final note

Dự án này không bắt đầu từ việc tôi biết lập trình.

Nó bắt đầu từ một câu hỏi đơn giản:

> **“Liệu tôi có thể biến quy trình Digital Marketing thành một hệ thống AI có cấu trúc, dễ kiểm soát và ngày càng thông minh hơn không?”**

Tôi vẫn đang tìm câu trả lời bằng cách tiếp tục xây dựng nó.
