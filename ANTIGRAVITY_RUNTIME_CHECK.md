# Antigravity Runtime Verification Guide (ANTIGRAVITY_RUNTIME_CHECK.md)

## 1. Overview & Discovery Standard

In Google Antigravity, workspace custom agents are discovered by parsing markdown definition files located at:
```text
.agents/agents/<agent_name>/agent.md
```

Each agent definition requires valid YAML frontmatter containing `name` and `description`:
```yaml
---
name: <agent_name>
description: <agent_description>
---
```

> **CRITICAL CAVEAT**: Unit tests validate directory presence and schema syntax, but **unit tests alone do not constitute runtime verification**. Runtime discovery must be verified directly inside the Antigravity environment.

---

## 2. Step-by-Step Manual Verification Procedure

### Step 1: Open Antigravity Workspace
Ensure the current workspace root is set to `c:/AI-Marketing-Department` (or your active repository clone).

### Step 2: Open Chat / Command Interface
Open the Antigravity interactive prompt in your active workspace.

### Step 3: Run the Agent Discovery Command
Type the following slash command in the chat box:
```text
/agents
```

### Step 4: Verify Available Agent List
Verify that the output list displays **EXACTLY FIVE** workspace custom agents:

| Agent Identifier | Name | Expected Description Summary |
|---|---|---|
| `cmo` | **cmo** | Chief Marketing Officer & Master Orchestrator |
| `intelligence` | **intelligence** | Market, Consumer, Product & Competitor Intelligence |
| `strategist` | **strategist** | Marketing Strategy & Growth specialist |
| `creative` | **creative** | Creative Director, Copywriter & Production Director |
| `performance` | **performance** | Performance Marketing, Analytics & Operations |

### Step 5: Verify Absence of Ghost / Duplicate Agents
- Confirm that no duplicate names exist.
- Confirm that no sixth permanent agent is listed.
- Confirm that all descriptions match their designated roles.

---

## 3. Troubleshooting & Failure Modes

If an agent does not appear after executing `/agents`:
1. **Check File Path**: Verify the file is strictly at `.agents/agents/<agent_name>/agent.md`.
2. **Check Frontmatter Syntax**: Verify that the frontmatter opens with `---` on Line 1, ends with `---`, and has valid YAML key-value pairs (`name: ...`, `description: ...`).
3. **Check Workspace Root**: Ensure the IDE workspace is opened at the repository root containing the `.agents` folder.
4. **Reload Workspace**: In Antigravity IDE, reload window or refresh agent cache if newly created files are not immediately indexed.
