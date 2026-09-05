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
- Hướng tới một **Unified Marketing Knowledge Platform** để người dùng có thể bổ sung, thay đổi và tái sử dụng kiến thức Content, Strategy, Ads, SEO, Social, Brand, Product, Image, Video, Design và Analytics mà không phải sửa Brain.
- Hướng tới một **provider-neutral creative capability layer** để agent có thể lập kế hoạch, viết prompt và gọi các model/API chuyên tạo ảnh, edit ảnh, tạo video, edit video, audio hoặc các tác vụ thiết kế khác.
- Giữ Human-in-the-Loop cho các hành động có ảnh hưởng thật như publishing, external writes hoặc ngân sách.
- Xây một nền tảng có thể tiếp tục mở rộng thêm skills, tools, plugins, knowledge packs và providers trong tương lai.

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
      ├─ Capability Registry
      ├─ Provider Registry
      └─ Universal Model Gateway
```

> Các service như Knowledge Router, Prompt Composer, Media Gateway, Artifact Manager hoặc Provider Adapter là **hạ tầng dùng chung**, không phải agent thứ 6. Kiến trúc logic của dự án vẫn giữ đúng **5 agent cố định**.

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

### Target architecture — Universal Capability / AI Provider Gateway

> **Planned / being hardened:** phần dưới mô tả hướng kiến trúc mục tiêu, không phải tuyên bố rằng toàn bộ capability và provider đã được triển khai production-ready ở commit hiện tại.

Mục tiêu dài hạn là mở rộng provider routing từ LLM sang nhiều loại AI capability, nhưng vẫn giữ Brain và 5 agent độc lập với vendor cụ thể.

```text
Five Agents
    │
    ▼
Capability / Tool Layer
    │
    ▼
Universal Capability Gateway
    │
    ├─ LLM Gateway
    ├─ Image Gateway
    ├─ Video Gateway
    ├─ Audio Gateway
    └─ Other AI / Design Capabilities
          │
          ▼
   Provider Registry + Adapters
```

Agent nên yêu cầu **capability**, không gọi tên vendor trực tiếp. Ví dụ:

```text
LLM_REASONING
IMAGE_GENERATE
IMAGE_EDIT
IMAGE_INPAINT
IMAGE_OUTPAINT
IMAGE_UPSCALE
BACKGROUND_REMOVE
VIDEO_GENERATE
VIDEO_EDIT
IMAGE_TO_VIDEO
VIDEO_EXTEND
VIDEO_UPSCALE
VIDEO_RESTYLE
LIP_SYNC
AUDIO_GENERATE
TEXT_TO_SPEECH
SPEECH_TO_TEXT
```

Provider Router / Adapter Layer sẽ chịu trách nhiệm chọn provider/model phù hợp, chuẩn hóa request/response, xử lý fallback, quota, retry và policy. Nhờ đó việc thêm một provider ảnh/video mới không nên buộc phải sửa logic cốt lõi của từng agent.

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

### Target architecture — Unified Marketing Knowledge Platform

> **Planned / incremental implementation:** Knowledge Platform dưới đây là hướng mở rộng của knowledge hiện có. Mọi trạng thái IMPLEMENTED / TESTED / RUNTIME_VERIFIED phải tiếp tục được xác nhận bằng code, test và `STATUS_MATRIX.md`.

Knowledge được định hướng thành một nền tảng dùng chung cho toàn bộ phòng Marketing, thay vì nhúng cứng kiến thức vào Brain hoặc nhân bản knowledge cho từng agent.

```text
Knowledge Platform
│
├─ Marketing Strategy
│  ├─ STP
│  ├─ 4P / 7P
│  ├─ Funnel
│  ├─ Positioning
│  ├─ Customer Journey
│  └─ Campaign Planning
│
├─ Content
│  ├─ Copywriting
│  ├─ Hooks
│  ├─ Storytelling
│  ├─ CTA
│  ├─ AIDA / PAS / BAB
│  ├─ Short-form / Long-form
│  └─ Brand Voice
│
├─ Paid Ads
│  ├─ Facebook Ads
│  ├─ Google Ads
│  ├─ TikTok Ads
│  ├─ Creative Strategy
│  ├─ Targeting
│  └─ Optimization
│
├─ SEO
├─ Social Media
├─ Creative
│  ├─ Image
│  ├─ Video
│  ├─ Design
│  └─ Audio
│
├─ Brand
├─ Product
├─ Customer
├─ Analytics
└─ Provider / Model Prompt Knowledge
```

Knowledge nên được chia theo **3 scope chính**:

1. **System Knowledge** — kiến thức Marketing/Creative tái sử dụng chung.
2. **Workspace / Brand Knowledge** — kiến thức riêng của doanh nghiệp, thương hiệu, sản phẩm hoặc workspace.
3. **Task / Campaign Knowledge** — file/context tạm thời dành cho campaign hoặc nhiệm vụ hiện tại.

Tại runtime, agent chỉ nên nhận knowledge liên quan đến task và capability hiện tại. Ví dụ:

```text
VIDEO_GENERATE
  → video knowledge
  → platform knowledge
  → brand knowledge
  → product knowledge
  → campaign knowledge

COPYWRITING
  → content knowledge
  → platform knowledge
  → brand knowledge
  → product knowledge
  → campaign knowledge
```

Cách này nhằm giảm context không liên quan, hạn chế tiêu thụ token và giảm nguy cơ knowledge leakage giữa scope.

### Knowledge Manager — target UX

Mục tiêu UI là cho phép người dùng quản lý knowledge mà không cần sửa source code:

```text
Knowledge Manager
│
├─ General Marketing
├─ Strategy
├─ Content
├─ Paid Ads
├─ SEO
├─ Social Media
├─ Image
├─ Video
├─ Design
├─ Analytics
├─ Brand
├─ Products
└─ Customers
```

Các thao tác mục tiêu:

- Add Knowledge;
- Upload File;
- Create Note;
- Edit;
- Enable / Disable;
- Delete;
- Version History;
- Assign to Agent;
- Assign to Capability.

Các định dạng ingest dự kiến ưu tiên gồm Markdown, text, PDF, DOCX và JSON khi phù hợp với parser/indexing pipeline.

Knowledge dùng chung sẽ được **scope theo agent/capability**, không copy thành nhiều bản riêng. Ví dụ một `brand/foxtech` knowledge source có thể được Creative, Strategist, Performance hoặc CMO tái sử dụng tùy task và permission.

---

## Creative / Media generation architecture

> **Target architecture / planned capability expansion.** Đây là workflow mục tiêu để biến kiến thức Marketing/Creative thành prompt và sau đó gọi model chuyên dụng. Nó không thay đổi nguyên tắc 5-agent cố định.

LLM/Brain chịu trách nhiệm suy luận, lập kế hoạch và chọn capability. Model chuyên ảnh/video/audio chịu trách nhiệm render media thực tế.

```text
User Request
    │
    ▼
Responsible Agent
    │
    ▼
Intent / Capability Selection
    │
    ▼
Knowledge Retriever
    │
    ├─ Marketing Knowledge
    ├─ Content / Creative Knowledge
    ├─ Platform Knowledge
    ├─ Brand Knowledge
    ├─ Product Knowledge
    └─ Campaign Knowledge
    │
    ▼
Creative / Content Planner
    │
    ▼
Prompt Composer
    │
    ▼
Capability Router
    │
    ▼
Provider Selection
    │
    ▼
Provider-specific Prompt Adapter
    │
    ▼
Image / Video / Audio API
    │
    ▼
Artifact Manager
    │
    ▼
Quality Evaluator
    │
    └─ revise / retry when policy allows
```

Provider-specific prompting rules nên được lưu ngoài Brain, ví dụ theo hướng:

```text
knowledge/providers/
├─ image-provider-a/
│  └─ prompting.md
├─ video-provider-a/
│  └─ prompting.md
├─ video-provider-b/
│  └─ prompting.md
└─ audio-provider-a/
   └─ prompting.md
```

Không nên nhúng các nhánh kiểu `if provider == ...` vào Brain. Việc khác biệt giữa API, model capability, input schema, polling job, output artifact hoặc prompt convention nên nằm ở Provider Adapter / Prompt Adapter / Capability Layer.

Các service hạ tầng mục tiêu cho media gồm:

- **Capability Registry** — biết hệ thống hiện có thể làm gì;
- **Provider Registry** — biết provider/model nào hỗ trợ capability nào;
- **Capability Router** — chọn đường thực thi phù hợp;
- **Adapter Layer** — chuẩn hóa API khác nhau;
- **Credential Manager** — quản lý API key/secret an toàn;
- **Media Artifact Manager** — quản lý ảnh/video/audio input-output và metadata;
- **Job Manager** — theo dõi các API render bất đồng bộ;
- **Fallback / Retry / Cost / Quota Policy** — quyết định khi nào đổi provider hoặc dừng an toàn.

Brain không cần biết chi tiết provider fallback nếu hạ tầng có thể xử lý minh bạch. Brain chủ yếu cần: **xác định capability → lấy đúng knowledge → lập kế hoạch → gọi tool → đánh giá kết quả → tiếp tục workflow**.

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

Trong roadmap, Settings/management UI cũng được định hướng để quản lý:

- LLM providers;
- Image providers;
- Video providers;
- Audio providers;
- API credentials;
- per-capability primary/fallback provider;
- Knowledge Manager và scope assignment.

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

> Image/video/audio provider configuration được mô tả ở phần target architecture phía trên và chỉ nên được coi là available khi code/test tại commit tương ứng xác nhận.

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
├─ knowledge/            # Knowledge system / future unified knowledge platform
├─ memory/               # Memory system
├─ runtime/              # Five-agent runtime / orchestration
├─ schemas/              # Typed domain contracts
├─ src-tauri/            # Tauri desktop shell
├─ tests/                # Regression / adversarial tests
├─ tools/                # Tool gateway & observation backends
├─ workspace/            # Business / project workspace scope
└─ run_app.ps1           # Local Windows launcher
```

Các module cụ thể cho media gateway, artifact/job management hoặc provider-specific prompt adapters có thể được bổ sung trong quá trình triển khai; README không giả định trước tên thư mục cuối cùng trước khi code được chốt.

---

## Trạng thái dự án

**Status: Active Development / Hardening**

Dự án đã có lượng code và test đáng kể, nhưng tôi vẫn đang tiếp tục:

- hardening kiến trúc;
- sửa regression;
- cải thiện agent intelligence;
- cải thiện memory/knowledge;
- xây dần Unified Marketing Knowledge Platform;
- hoàn thiện provider interoperability;
- mở rộng capability routing cho image/video/audio/design;
- phát triển workflow knowledge → planning → prompt → provider → artifact → evaluation;
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