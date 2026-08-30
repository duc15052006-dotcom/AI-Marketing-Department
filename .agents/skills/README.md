# Five-Agent Skill Workspace

This directory contains procedural skill modules for the five permanent logical agents only:
CMO, Intelligence, Strategist, Creative, and Performance.

Final CMO is the CMO's second workflow pass and is not a sixth agent.

## Safety and authority

Skills are procedural guidance, not independent authorities. They never bypass Model Gateway, Tool Gateway, PolicyEngine, approval gates, evidence validation, tenant scope, or secret boundaries. A skill cannot claim a tool executed, a source was verified, or an external action occurred without the corresponding trusted runtime evidence/receipt.

The production runtime authority remains `runtime/agent_skills.py`. These `SKILL.md` files are progressive-disclosure resources that can later be compiled by the Agent Execution Kernel without hard-coding a provider or connector.
