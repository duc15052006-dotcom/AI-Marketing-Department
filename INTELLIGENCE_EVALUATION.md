# AI Intelligence Specialist Evaluation & Benchmark Suite (INTELLIGENCE_EVALUATION.md)

## 1. Overview & Evaluation Philosophy

This evaluation suite defines the behavioral benchmark criteria used to audit, test, and validate the research rigor, epistemic fidelity, and commercial awareness of the **Market & Consumer Intelligence Specialist**.

The Intelligence Specialist acts as the empirical evidence engine of the marketing department. These 15 deterministic benchmark scenarios evaluate how the agent handles misinformation, viral hype, source circularity, sampling biases, Say vs. Do divergence, demand signal triangulation, confidence calibration, and epistemic boundaries.

---

## 2. The 15 Executive Benchmark Scenarios

### Scenario 1: Viral Product with Strong Attention but No Transaction Evidence
- **INPUT**:
  Strategist: *"A fidget spinner video just hit 15 million views on TikTok with 1.2M likes and 45k shares in 48 hours. Research this and confirm if this represents a massive new $10M category demand for our e-commerce store."*
- **EXPECTED INTELLIGENCE BEHAVIOR**:
  - Uses demand signal taxonomy to classify the 15M views as an **Attention Signal**, not a validated **Purchase_Intent** or **Transaction Signal**.
  - Triangulates available signals: search velocity, marketplace listing changes, comment intent.
  - Explains that while top-of-funnel reach is high, commercial buying demand, margin viability, and unit economics remain unproven hypotheses.
  - Flags the high risk of a transient viral meme vs durable category demand.
- **FAILURE CONDITIONS**:
  - Reports that 15M views equals validated multi-million dollar commercial market demand.
  - Fails to distinguish attention from commercial purchase intent.
- **EVALUATION CRITERIA**:
  - `Signal Taxonomy Distinction`: 100% (Separates Attention from Transaction signals).
  - `Epistemic Discipline`: Rejects popularity as proof of demand.

---

### Scenario 2: Ten Websites Repeating One Original Source (Circular Citation)
- **INPUT**:
  Researcher query: *"Verify whether 82% of all enterprise buyers choose vendor solutions exclusively based on LinkedIn thought leadership, as claimed across 10 industry blogs."*
- **EXPECTED INTELLIGENCE BEHAVIOR**:
  - Traces the claim back through the citation chain to its primary origin.
  - Discovers that all 10 blog articles cite a single 2019 marketing agency infographic derived from an unweighted 35-person survey.
  - Explicitly documents that 10 syndication instances represent **one** weak primary source, not 10 independent corroborating data points.
  - Assigns `CONFIDENCE: LOW` with explicit `CONFIDENCE_RATIONALE` detailing sample size limitations ($N=35$).
- **FAILURE CONDITIONS**:
  - Reports that the claim is confirmed by 10 independent authoritative sources.
  - Counts syndicated repetitions as corroborating evidence.
- **EVALUATION CRITERIA**:
  - `Forensic Source Tracing`: Uncovers single primary origin.
  - `Circular Citation Detection`: Rejects artificial evidence inflation.

---

### Scenario 3: Outdated Platform Policy Presented as Current
- **INPUT**:
  Creative: *"What are Meta's ad text overlay rules? I remember there was a strict 20% text limit rule that automatically rejects ad graphics if text exceeds 20% of the image."*
- **EXPECTED INTELLIGENCE BEHAVIOR**:
  - Recognizes that platform ad rules change over time (Meta removed the strict 20% text penalty rule in late 2020).
  - Checks live/recent platform documentation with exact timestamps (`OBSERVED_AT`, `SOURCE_DATE`).
  - Reports that the 20% rule is an outdated policy, providing the current guidelines (text density still affects delivery pacing, but hard rejection is deprecated).
  - Flags `FRESHNESS_RISK: HIGH` on historical documentation.
- **FAILURE CONDITIONS**:
  - Confirms the obsolete 20% text rule as current policy based on pre-2020 static training weights.
  - Omits publication dates and timestamps on platform policy claims.
- **EVALUATION CRITERIA**:
  - `Freshness Protocol Enforcement`: Validates current policy state.
  - `Time-Decay Awareness`: Corrects obsolete platform assumptions.

---

### Scenario 4: Review Sample Percentage Incorrectly Generalized to All Customers
- **INPUT**:
  Research prompt: *"In our scrape of 200 Amazon customer reviews for our noise-canceling headphones, 80 reviews (40%) mentioned battery degradation after 6 months. Summarize this for executive leadership."*
- **EXPECTED INTELLIGENCE BEHAVIOR**:
  - Adheres strictly to **Sample Percentage Discipline**:
    - **Allowed formulation**: *"Within this sample of 200 analyzed Amazon reviews, 40% (80 reviews) mentioned battery degradation."*
    - **Explicit qualification**: Notes that review datasets have self-selection bias (dissatisfied customers are disproportionately motivated to write reviews).
  - Refuses to claim: *"40% of all our customers have battery problems."*
  - Specifies `SAMPLE_SIZE: 200`, `PLATFORM: Amazon US`, `KNOWN_BIAS: Self-selection / negative review motivation`.
- **FAILURE CONDITIONS**:
  - Generalizes the sample percentage to the entire customer population (*"40% of our total customer base experiences battery failure"*).
  - Fails to qualify the sample boundaries and platform biases.
- **EVALUATION CRITERIA**:
  - `Sample Percentage Discipline`: 100% compliance with `WITHIN_THIS_SAMPLE` qualification.
  - `Bias Auditing`: Identifies self-selection review skew.

---

### Scenario 5: Stated Preference vs Observed Behavior Divergence (Say vs. Do Triangulation)
- **INPUT**:
  Product dataset:
  - Survey Data: 78% of active users state in quarterly surveys that they want an advanced, customizable reporting dashboard.
  - Product Telemetry: Only 3.2% of daily active users ever click the reporting tab.
- **EXPECTED INTELLIGENCE BEHAVIOR**:
  - Avoids declaring telemetry as absolute truth that disproves user desire, and avoids declaring survey results as the sole mandate.
  - Triangulates between **What People Say**, **What People Do**, **Context**, **Constraints**, and **Incentives**.
  - Analyzes potential root-cause explanations for the discrepancy:
    1. *Discoverability / UX Friction*: Is the reporting tab hidden three levels deep?
    2. *Social Desirability Bias*: Do users feel they *should* want advanced analytics when asked in surveys?
    3. *Complexity Barrier*: Do users desire the outcome of advanced reporting but find the current builder too complex?
    4. *Habit / Workflow Inertia*: Are users exporting raw CSVs into spreadsheets because of existing routines?
  - Recommends qualitative usability interviews or in-app discovery tests to isolate the constraint before abandoning or over-investing in the feature.
- **FAILURE CONDITIONS**:
  - Declares behavioral telemetry as universally superior ground truth and dismisses survey feedback as worthless noise.
  - Ignores the telemetry and recommends building an expensive dashboard based solely on survey responses.
- **EVALUATION CRITERIA**:
  - `Say vs Do Triangulation`: Avoids absolute priority to either source.
  - `Root-Cause Discrepancy Analysis`: Probes usability, discoverability, and psychological barriers.

---

### Scenario 6: Behavior Constrained by Poor UX / Access Barriers
- **INPUT**:
  Telemetry vs Stated Need: Users in customer support tickets frequently complain about difficulty exporting team billing invoices. Telemetry shows 0.1% usage of the self-serve "Export PDF Invoice" button.
- **EXPECTED INTELLIGENCE BEHAVIOR**:
  - Investigates environmental and UX constraints before interpreting 0.1% usage as "lack of user need".
  - Discovers that the button is located inside an obscure sub-menu labeled "Legacy Organization Admin" requiring 4 clicks and desktop browser view.
  - Concludes that low observed behavior is an **Artifact of Severe UX Friction & Poor Discoverability**, not evidence of low demand.
  - Frames the invoice export as a validated customer need with an urgent UX accessibility fix required.
- **FAILURE CONDITIONS**:
  - Concludes from 0.1% telemetry that users do not care about exporting invoices.
  - Fails to evaluate UX friction and accessibility constraints.
- **EVALUATION CRITERIA**:
  - `Constraint-Aware Analysis`: Identifies UX friction as the suppressor of observed behavior.
  - `Epistemic Balance`: Protects valid customer needs from naive telemetry interpretation.

---

### Scenario 7: Fake / Fabricated Source Detection
- **INPUT**:
  External report submission: *"A research paper titled 'The 2026 Conversion Optimization Index by Global Digital Institute' (url: 'https://digital-insights-fake2026.org/report') claims video ads without captions convert 80% worse."*
- **EXPECTED INTELLIGENCE BEHAVIOR**:
  - Attempts forensic verification of the source, domain, and author.
  - Identifies that the domain is invalid/unresolvable, author is unlisted, and Global Digital Institute has no verifiable registry or published methodology.
  - Rejects the report deliverable as `UNVERIFIED / FABRICATED EVIDENCE`.
  - Identifies legitimate, verifiable benchmark studies on vertical video captioning (e.g., industry data showing ~70-80% of mobile users watch with sound off).
- **FAILURE CONDITIONS**:
  - Accepts the fake URL and fabricated institution as authoritative fact.
  - Cites the unverified paper in strategic recommendations.
- **EVALUATION CRITERIA**:
  - `Zero Tolerance for Fabricated Data`: 100% rejection rate.
  - `Evidence Verification`: Replaces fake source with verified primary benchmarks.

---

### Scenario 8: Macro Trend vs One-Time Viral Spike
- **INPUT**:
  Trend query: *"A single meme sound clip 'Cat Dance 2026' was used in 500,000 videos over the weekend. Is this a permanent macro consumer trend we should anchor our 6-month product roadmap to?"*
- **EXPECTED INTELLIGENCE BEHAVIOR**:
  - Classifies 'Cat Dance 2026' as a short-lived **Viral Spike / Platform Meme** (expected lifecycle: 5–14 days), not a structural Macro Trend.
  - Evaluates trend metrics: High acceleration and velocity, but near-zero duration, zero cross-category commercial intent, and rapid saturation decay.
  - Recommends Creative Agent use the audio immediately for organic social engagement if brand-aligned, but warns against building long-term campaign architecture or product roadmaps around it.
- **FAILURE CONDITIONS**:
  - Declares the viral meme a 6-month macro consumer trend.
  - Recommends changing core product features based on a weekend audio spike.
- **EVALUATION CRITERIA**:
  - `Trend Taxonomy Accuracy`: Distinguishes Macro Trend from Viral Spike.
  - `Temporal Horizon Modeling`: Estimates accurate lifecycle decay.

---

### Scenario 9: Demographic-Only Customer Persona vs Multi-Dimensional JTBD
- **INPUT**:
  Marketing brief: *"Our customer persona is: 'Men and Women aged 25-45 who live in suburban areas and make $60,000/year.' Flesh this out for the Creative team."*
- **EXPECTED INTELLIGENCE BEHAVIOR**:
  - Challenges the demographic-only definition as superficial and insufficient for high-converting marketing.
  - Conducts Jobs-to-Be-Done (JTBD) and psychological discovery to build a deep customer profile:
    - Context & Moment of Need (When does the acute pain occur?).
    - Core Functional & Emotional JTBD.
    - Acute Pains, Hidden Anxieties, and Frustrations.
    - Buying Triggers and High-Friction Objections.
    - Exact verbatim customer vocabulary and pain phrases.
  - Delivers a structured `CustomerPersona` schema that equips Creative with emotional hooks and Strategist with clear positioning angles.
- **FAILURE CONDITIONS**:
  - Accepts the flat age/income bucket without expanding into JTBD, pains, desires, or objections.
- **EVALUATION CRITERIA**:
  - `Deep Customer Anatomy`: Generates multi-dimensional behavioral insight.
  - `Actionable Handoff`: Provides verbatim language for Creative.

---

### Scenario 10: Unavailable Transaction Data Incorrectly Interpreted as Zero Demand
- **INPUT**:
  Market research inquiry: *"We want to evaluate commercial demand for our upcoming enterprise on-premise AI privacy firewall. Our internal CRM has zero historical sales for this new product category. Does this mean zero market demand exists?"*
- **EXPECTED INTELLIGENCE BEHAVIOR**:
  - Clarifies that lack of historical transaction data in our CRM indicates an **Unobserved / Pre-Launch State**, not evidence of "zero market demand".
  - Explains that transaction data is channel-specific and currently unavailable for this new offering.
  - Triangulates upstream demand signals: competitor enterprise pricing pages, Gartner inquiry trends, search volume growth for "on-premise LLM compliance", and customer support requests for local hosting.
  - Concludes that strong upstream interest and consideration signals exist, recommending a pilot MVP or customer discovery sprint.
- **FAILURE CONDITIONS**:
  - Concludes that zero CRM transactions proves the market has zero demand for privacy firewalls.
  - Treats absence of internal transaction records as proof of absence of customer need.
- **EVALUATION CRITERIA**:
  - `Signal Triangulation`: Probes upstream indicators when transaction data is unavailable.
  - `Epistemic Sophistication`: Avoids false zero-demand deductions.

---

### Scenario 11: Cross-Product Context Contamination (Multi-Tenant Isolation)
- **INPUT**:
  Research dispatch in product workspace `PROD-SAAS-AI`: *"Conduct competitor intelligence on customer retention tactics for our B2B Enterprise AI Code Assistant."*
  (Agent has past research in memory for `PROD-COSMETIC-02` e-commerce loyalty programs).
- **EXPECTED INTELLIGENCE BEHAVIOR**:
  - Strictly respects product partition key `product_id: PROD-SAAS-AI`.
  - Filters all memory queries and research context to developer tools, developer productivity, enterprise IT procurement, and B2B SaaS retention benchmarks.
  - Completely excludes retail cosmetic loyalty points, unboxing gifts, or B2C influencer referral data.
  - Confirms zero cross-tenant contamination in output metadata.
- **FAILURE CONDITIONS**:
  - Suggests cosmetic loyalty punch-cards or retail beauty promotions for the enterprise developer tool.
  - Leaks competitor data from other product workspaces.
- **EVALUATION CRITERIA**:
  - `Product Isolation Compliance`: 100% tenant separation.
  - `Contextual Coherence`: Strictly aligns intelligence with active domain.

---

### Scenario 12: Insufficient Information Requiring Explicit "UNKNOWN"
- **INPUT**:
  User: *"What is the exact monthly ad spend of our stealth competitor 'Acme Stealth Labs' on Snapchat in Japan for Q1 2026?"*
- **EXPECTED INTELLIGENCE BEHAVIOR**:
  - Checks available public ad repositories and observation sources.
  - Determines that Acme Stealth Labs has no public Japanese entity, Snapchat ad transparency data is unavailable for that specific region/entity, and private spend figures are not publicly disclosed.
  - Explicitly states `UNKNOWN / INSUFFICIENT DATA` rather than inventing an estimated dollar amount.
  - Details what *can* be observed (e.g., whether Japanese localization exists, app store ranking) and outlines proxy methods to monitor future entry.
- **FAILURE CONDITIONS**:
  - Invents a specific dollar figure (e.g., *"They spend roughly $45,000/month"*) with no verifiable evidence.
  - Fails to report the knowledge gap as UNKNOWN.
- **EVALUATION CRITERIA**:
  - `Epistemic Honesty`: Transparent reporting of unknown data.
  - `Anti-Hallucination Discipline`: Refuses to guess private financial figures.

---

### Scenario 13: Unjustified Numeric Pseudo-Precision (Confidence Calibration)
- **INPUT**:
  Draft findings review: An intelligence subagent outputs *"Conclusion: 93.4% of prospective SMB buyers prefer monthly pricing over annual pricing (Confidence: 0.93)"* based on a casual Reddit thread with 14 upvotes.
- **EXPECTED INTELLIGENCE BEHAVIOR**:
  - Rejects the pseudo-precise confidence score (`0.93`) and percentage (`93.4%`).
  - Explains that decimal-precision numbers derived from small, uncalibrated forum threads create a false illusion of mathematical certainty.
  - Recalibrates output to qualitative tier: `CONFIDENCE: LOW`.
  - Provides a mandatory `CONFIDENCE_RATIONALE`: *"Finding is based on a single unweighted Reddit discussion with self-selection bias and no formal statistical sampling."*
- **FAILURE CONDITIONS**:
  - Transmits the 0.93 confidence score and 93.4% figure to the CMO without challenge.
  - Fails to provide a clear confidence rationale.
- **EVALUATION CRITERIA**:
  - `Anti-Pseudo-Precision`: Rejects arbitrary mathematical precision on qualitative samples.
  - `Confidence Rationale Quality`: Explains exact evidence limitations.

---

### Scenario 14: Research Rabbit Hole & Stopping Rule
- **INPUT**:
  Research execution loop: Agent has gathered 35 verified competitor pricing pages, 150 customer reviews, and official platform guidelines confirming that Competitor A charges $29/mo with high customer satisfaction. The user has allocated a 15-minute / 5-query research budget.
- **EXPECTED INTELLIGENCE BEHAVIOR**:
  - Evaluates the **Research Stopping Rule**: Core question is answered with high confidence, additional queries provide diminishing marginal value, and budget limit is reached.
  - Concludes research and synthesizes the standard `ResearchReport` deliverable.
  - Documents residual minor unknowns as future hypotheses rather than continuing to search indefinitely.
- **FAILURE CONDITIONS**:
  - Continues issuing redundant search queries looking for identical pricing data across obscure secondary forums.
  - Fails to terminate research when information value diminishes.
- **EVALUATION CRITERIA**:
  - `Stopping Rule Adherence`: Terminates upon achieving decision sufficiency.
  - `Resource Efficiency`: Maximizes information density per query.

---

### Scenario 15: Commercial Inference Unsupported by Transaction Evidence
- **INPUT**:
  Data observation: A software productivity app has 100,000 free Discord community members and 50,000 GitHub stars, but only 12 paid enterprise customers.
- **EXPECTED INTELLIGENCE BEHAVIOR**:
  - Correctly separates community engagement and developer appreciation (**Attention & Interest Signals**) from enterprise willingness-to-pay (**Transaction Signals**).
  - Notes that open-source stars and Discord chatter indicate high developer enthusiasm but do not inherently validate enterprise procurement or commercial monetization.
  - Categorizes the claim *"We have proven enterprise product-market fit"* as a **Refuted Inference / Unsupported Hypothesis**.
  - Recommends investigating enterprise procurement barriers, security certifications, and team permission controls.
- **FAILURE CONDITIONS**:
  - Reports that 50k GitHub stars proves strong enterprise revenue viability.
  - Confuses open-source enthusiast adoption with paying enterprise customer demand.
- **EVALUATION CRITERIA**:
  - `Commercial Synthesis Rigor`: Strictly distinguishes vanity/community metrics from revenue proof.
  - `Barrier Identification`: Diagnoses the monetization gap.
